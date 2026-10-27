//! Supervision (one engine at a time, a generation per start, restarts with backoff), the call path, and the event
//! relay. Pending calls fail when the engine goes away; nothing here resumes a job (ADR 0015, "Restarts").

use std::{
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use eventsource_stream::Eventsource;
use futures_util::StreamExt;
use serde::Serialize;
use serde_json::{Map, Value, json};
use tokio::sync::{broadcast, watch};
use url::Url;

use crate::{
    contract::{Operation, build_url, operation},
    engine::{self, EngineCommand, Tree},
    error::GatewayError,
};

const CALL_TIMEOUT: Duration = Duration::from_secs(60);
const BACKOFF_FIRST: Duration = Duration::from_millis(500);
const BACKOFF_MAX: Duration = Duration::from_secs(30);
const QUICK_EXIT: Duration = Duration::from_secs(10); // an engine that dies this soon counts towards giving up
const QUICK_EXITS_ALLOWED: u32 = 5;
const STOP_GRACE: Duration = Duration::from_secs(5); // how long a stopping engine gets before its tree is ended

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EngineState {
    Starting,
    Ready,
    Restarting,
    Failed,
    Stopped,
}

#[derive(Debug, Clone, Serialize)]
pub struct Status {
    pub generation: u64,
    pub state: EngineState,
    pub engine_version: Option<String>,
    /// The contract the engine's handshake announced (when ready).
    pub contract: Option<String>,
    pub message: Option<String>,
    /// Why it is Failed: `contract_mismatch`, `engine_refused` or `crash_loop`.
    pub code: Option<String>,
}

impl Status {
    fn new(generation: u64, state: EngineState) -> Self {
        Status {
            generation,
            state,
            engine_version: None,
            contract: None,
            message: None,
            code: None,
        }
    }

    fn with_message(mut self, message: impl Into<String>) -> Self {
        self.message = Some(message.into());
        self
    }

    fn with_code(mut self, code: &str) -> Self {
        self.code = Some(code.to_owned());
        self
    }
}

/// What the web view receives on its event channel.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum GatewayEvent {
    /// The engine's state changed; a new generation means every job and event of an older one is gone.
    Engine(Status),
    /// One engine event `{seq, job_id, type, data}`, unchanged, with the generation that sent it.
    Event {
        generation: u64,
        seq: u64,
        job_id: Option<String>,
        r#type: String,
        data: Value,
    },
    /// This subscriber fell behind and missed events: reload what is shown.
    Lagged { missed: u64 },
}

#[derive(Clone)]
struct Conn {
    generation: u64,
    base: Url,
    token: String,
}

struct Inner {
    command: EngineCommand,
    client: reqwest::Client,
    conn: Mutex<Option<Conn>>,
    tree: Mutex<Option<Arc<Tree>>>,
    status: Mutex<Status>,
    events: broadcast::Sender<GatewayEvent>,
    stop: watch::Sender<bool>,
}

#[derive(Clone)]
pub struct Gateway {
    inner: Arc<Inner>,
}

impl Gateway {
    /// Starts supervising the engine in the background (call from inside a Tokio runtime) and returns at once.
    pub fn start(command: EngineCommand) -> Self {
        // reqwest is built without a TLS provider when another crate in the app (Tauri's updater) asks for
        // `rustls-no-provider`, and creating the client then panics; install one process-wide, once
        let _ = rustls::crypto::ring::default_provider().install_default();
        let (events, _) = broadcast::channel(1024);
        let inner = Arc::new(Inner {
            command,
            client: reqwest::Client::builder()
                .no_proxy()
                .build()
                .expect("an HTTP client"),
            conn: Mutex::new(None),
            tree: Mutex::new(None),
            status: Mutex::new(Status::new(0, EngineState::Starting)),
            events,
            stop: watch::channel(false).0,
        });
        tokio::spawn(supervise(inner.clone()));
        Gateway { inner }
    }

    pub fn status(&self) -> Status {
        self.inner.status.lock().unwrap().clone()
    }

    pub fn subscribe(&self) -> broadcast::Receiver<GatewayEvent> {
        self.inner.events.subscribe()
    }

    /// Calls one allowlisted operation. `path` and `query` hold parameter values by name; the URL is built here.
    pub async fn call(
        &self,
        operation_id: &str,
        path: Map<String, Value>,
        query: Map<String, Value>,
        body: Option<Value>,
    ) -> Result<Value, GatewayError> {
        let op = operation(operation_id)?;
        let body = body.filter(|b| !b.is_null());
        if op.has_body && body.is_none() {
            return Err(GatewayError::bad_parameter("body", "required"));
        }
        if !op.has_body && body.is_some() {
            return Err(GatewayError::bad_parameter(
                "body",
                "this operation takes none",
            ));
        }
        let conn = self
            .inner
            .conn
            .lock()
            .unwrap()
            .clone()
            .ok_or_else(|| GatewayError::engine_unavailable("The engine is not running."))?;
        let url = build_url(&conn.base, op, &path, &query)?;
        let method = reqwest::Method::from_bytes(op.method.as_bytes())
            .expect("an HTTP method from the contract");
        let mut request = self
            .inner
            .client
            .request(method, url)
            .bearer_auth(&conn.token)
            .timeout(CALL_TIMEOUT);
        if let Some(body) = body {
            request = request.json(&body);
        }
        let response = request.send().await.map_err(|e| {
            if e.is_timeout() {
                GatewayError::gateway(
                    504,
                    "timeout",
                    "The engine did not answer in time.",
                    Value::Null,
                )
            } else {
                GatewayError::engine_unavailable("The engine went away during the call.")
            }
        })?;
        let status = response.status();
        let bytes = response.bytes().await.map_err(|_| {
            GatewayError::engine_unavailable("The engine went away during the call.")
        })?;
        if status.is_success() {
            Ok(if bytes.is_empty() {
                Value::Null
            } else {
                serde_json::from_slice(&bytes).unwrap_or(Value::Null)
            })
        } else {
            Err(GatewayError::from_engine(status.as_u16(), &bytes))
        }
    }

    /// Like `call`, with one flat object of parameters split by the contract: names the operation lists as path or
    /// query parameters go there, the rest is the JSON body (refused when the operation takes none).
    pub async fn call_params(
        &self,
        operation_id: &str,
        params: Map<String, Value>,
    ) -> Result<Value, GatewayError> {
        let op = operation(operation_id)?;
        let (path, query, body) = split_params(op, params)?;
        self.call(operation_id, path, query, body).await
    }

    /// Ends the running engine's whole process tree, as a crash would (development and tests: the restart path).
    pub fn kill_engine(&self) {
        if let Some(tree) = self.inner.tree.lock().unwrap().clone() {
            tree.kill();
        }
    }

    /// Stops supervising: the engine is asked to stop (stdin closed), then its process tree is ended after a grace
    /// period. Returns once it is stopped, or after `wait`.
    pub async fn shutdown(&self, wait: Duration) {
        self.inner.stop.send_replace(true);
        let mut events = self.subscribe();
        let deadline = tokio::time::Instant::now() + wait;
        while self.status().state != EngineState::Stopped
            && self.status().state != EngineState::Failed
        {
            if tokio::time::timeout_at(deadline, events.recv())
                .await
                .is_err()
            {
                self.kill_engine();
                break;
            }
        }
    }

    /// Starts the engine again (the recovery screen's Retry): a new supervisor after one that gave up or was stopped,
    /// or a fresh process when one is running.
    pub fn restart(&self) {
        match self.status().state {
            EngineState::Failed | EngineState::Stopped => {
                self.inner.stop.send_replace(false); // send() fails, unchanged, once the old supervisor has gone
                tokio::spawn(supervise(self.inner.clone()));
            }
            _ => self.kill_engine(),
        }
    }
}

fn set_status(inner: &Inner, status: Status) {
    *inner.status.lock().unwrap() = status.clone();
    let _ = inner.events.send(GatewayEvent::Engine(status));
}

type Split = (Map<String, Value>, Map<String, Value>, Option<Value>);

fn split_params(op: &Operation, params: Map<String, Value>) -> Result<Split, GatewayError> {
    let (mut path, mut query, mut rest) = (Map::new(), Map::new(), Map::new());
    for (name, value) in params {
        let target = if op.path_params.contains(&name.as_str()) {
            &mut path
        } else if op.query_params.contains(&name.as_str()) {
            &mut query
        } else {
            &mut rest
        };
        target.insert(name, value);
    }
    if !op.has_body {
        if let Some(name) = rest.keys().next() {
            return Err(GatewayError::bad_parameter(
                name,
                "not a parameter of this operation",
            ));
        }
        return Ok((path, query, None));
    }
    Ok((path, query, Some(Value::Object(rest))))
}

async fn supervise(inner: Arc<Inner>) {
    let mut stop = inner.stop.subscribe();
    let mut generation = inner.status.lock().unwrap().generation; // a restarted supervisor keeps counting
    let mut backoff = BACKOFF_FIRST;
    let mut quick_exits = 0;
    loop {
        if *stop.borrow() {
            break;
        }
        generation += 1;
        set_status(&inner, Status::new(generation, EngineState::Starting));
        match engine::start(&inner.command).await {
            Ok(mut running) => {
                let base =
                    Url::parse(&format!("http://127.0.0.1:{}/", running.handshake.port)).unwrap();
                *inner.conn.lock().unwrap() = Some(Conn {
                    generation,
                    base,
                    token: running.token.clone(),
                });
                *inner.tree.lock().unwrap() = Some(running.tree.clone());
                set_status(
                    &inner,
                    Status {
                        engine_version: Some(running.handshake.version.clone()),
                        contract: Some(running.handshake.contract.clone()),
                        ..Status::new(generation, EngineState::Ready)
                    },
                );
                let (relay_stop, relay_rx) = watch::channel(false);
                let conn = inner.conn.lock().unwrap().clone().unwrap();
                tokio::spawn(relay(inner.clone(), conn, relay_rx));
                let since = Instant::now();
                let exit = tokio::select! {
                    exit = running.child.wait() => exit.ok().and_then(|s| s.code()),
                    _ = stop.changed() => {
                        running.close_stdin(); // graceful first; the tree is ended if it is not gone in time
                        if tokio::time::timeout(STOP_GRACE, running.child.wait()).await.is_err() {
                            running.tree.kill();
                            let _ = running.child.wait().await;
                        }
                        None
                    }
                };
                let _ = relay_stop.send(true);
                *inner.conn.lock().unwrap() = None; // calls from here on fail; calls in flight fail with the socket
                *inner.tree.lock().unwrap() = None;
                if *stop.borrow() {
                    break;
                }
                quick_exits = if since.elapsed() < QUICK_EXIT {
                    quick_exits + 1
                } else {
                    0
                };
                if since.elapsed() >= QUICK_EXIT {
                    backoff = BACKOFF_FIRST;
                }
                if quick_exits > QUICK_EXITS_ALLOWED {
                    set_status(
                        &inner,
                        Status::new(generation, EngineState::Failed)
                            .with_message(format!(
                                "The engine keeps stopping (last exit {exit:?})."
                            ))
                            .with_code("crash_loop"),
                    );
                    return;
                }
                set_status(
                    &inner,
                    Status::new(generation, EngineState::Restarting)
                        .with_message(format!("The engine stopped (exit {exit:?}).")),
                );
            }
            Err(e)
                if e.code == "gateway.engine_refused" || e.code == "gateway.contract_mismatch" =>
            {
                let code = e.code.trim_start_matches("gateway.").to_owned();
                set_status(
                    &inner,
                    Status::new(generation, EngineState::Failed)
                        .with_message(e.message)
                        .with_code(&code),
                ); // a restart cannot fix it
                return;
            }
            Err(e) => {
                quick_exits += 1;
                if quick_exits > QUICK_EXITS_ALLOWED {
                    set_status(
                        &inner,
                        Status::new(generation, EngineState::Failed)
                            .with_message(e.message)
                            .with_code("crash_loop"),
                    );
                    return;
                }
                set_status(
                    &inner,
                    Status::new(generation, EngineState::Restarting).with_message(e.message),
                );
            }
        }
        tokio::select! {
            _ = tokio::time::sleep(backoff) => {}
            _ = stop.changed() => break,
        }
        backoff = (backoff * 2).min(BACKOFF_MAX);
    }
    set_status(&inner, Status::new(generation, EngineState::Stopped));
}

/// One SSE connection to `/v1/events` for one engine generation, forwarded in order. A dropped stream reconnects with
/// Last-Event-ID to the same process; a new generation starts a new relay with no replay (the ring buffer died with it).
async fn relay(inner: Arc<Inner>, conn: Conn, mut stop: watch::Receiver<bool>) {
    let mut last_seq: Option<u64> = None;
    let url = conn.base.join("v1/events").unwrap();
    loop {
        let mut request = inner.client.get(url.clone()).bearer_auth(&conn.token);
        if let Some(seq) = last_seq {
            request = request.header("Last-Event-ID", seq.to_string());
        }
        if let Ok(response) = request.send().await
            && response.status().is_success()
        {
            let mut stream = response.bytes_stream().eventsource();
            loop {
                tokio::select! {
                    _ = stop.changed() => return,
                    item = stream.next() => match item {
                        Some(Ok(event)) => {
                            let Ok(envelope) = serde_json::from_str::<Value>(&event.data) else { continue };
                            let Some(seq) = envelope.get("seq").and_then(Value::as_u64) else { continue };
                            if last_seq.is_some_and(|last| seq <= last) {
                                continue; // replayed after a reconnect and already forwarded
                            }
                            last_seq = Some(seq);
                            let _ = inner.events.send(GatewayEvent::Event {
                                generation: conn.generation,
                                seq,
                                job_id: envelope.get("job_id").and_then(Value::as_str).map(str::to_owned),
                                r#type: envelope.get("type").and_then(Value::as_str).unwrap_or_default().to_owned(),
                                data: envelope.get("data").cloned().unwrap_or(json!(null)),
                            });
                        }
                        _ => break,
                    }
                }
            }
        }
        tokio::select! {
            _ = stop.changed() => return,
            _ = tokio::time::sleep(Duration::from_millis(250)) => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn split(id: &str, params: Value) -> Result<Split, GatewayError> {
        split_params(operation(id).unwrap(), params.as_object().unwrap().clone())
    }

    #[test]
    fn params_split_into_path_and_body_by_the_contract() {
        let (path, query, body) = split("get_job", json!({ "job_id": "a" })).unwrap();
        assert_eq!(
            (path["job_id"].clone(), query.len(), body),
            (json!("a"), 0, None)
        );
        let (_, _, body) = split("saves_back_up", json!({ "everything": true })).unwrap();
        assert_eq!(body, Some(json!({ "everything": true })));
        // a body operation with nothing to send still gets an object
        let (_, _, body) = split("saves_back_up", json!({})).unwrap();
        assert_eq!(body, Some(json!({})));
    }

    #[test]
    fn query_names_go_to_the_query() {
        let op = Operation {
            id: "x",
            method: "GET",
            path: "/v1/x/{id}",
            path_params: &["id"],
            query_params: &["limit"],
            has_body: false,
        };
        let params = json!({ "id": "a", "limit": 5 })
            .as_object()
            .unwrap()
            .clone();
        let (path, query, body) = split_params(&op, params).unwrap();
        assert_eq!(
            (path.len(), query["limit"].clone(), body),
            (1, json!(5), None)
        );
    }

    #[test]
    fn leftovers_with_no_body_are_a_bad_parameter() {
        let err = split("get_job", json!({ "job_id": "a", "extra": 1 })).unwrap_err();
        assert_eq!(err.code, "gateway.bad_parameter");
    }
}
