//! The shapes the React UI receives (bayle-ui `src/api/gateway/protocol.ts`): the gateway's status and events in the
//! UI's words, and errors as `{code, message, details}`. Pure mapping, no Tauri types, so it is unit-tested here.

use bayle_gateway::{EngineState, GatewayError, GatewayEvent, Status};
use serde::Serialize;
use serde_json::Value;

pub const PROTOCOL: u32 = 1;
const MAX_PROBLEM: usize = 300;

#[derive(Debug, Serialize, PartialEq)]
pub struct Problem {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct EngineStatus {
    pub state: &'static str,
    pub epoch: u64,
    pub protocol: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub engine_version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub contract: Option<String>,
    pub expected_contract: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub problem: Option<Problem>,
}

#[derive(Debug, Serialize, PartialEq)]
pub struct UiEvent {
    pub epoch: u64,
    pub seq: u64,
    pub job_id: Option<String>,
    pub r#type: String,
    pub data: Value,
}

#[derive(Debug, Serialize, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum UiMessage {
    Status { status: EngineStatus },
    Event { event: UiEvent },
}

/// Folders a message must not name, each with its stand-in. List the most specific first (the install folder may sit under home).
pub struct Redact(pub Vec<(String, &'static str)>);

impl Redact {
    fn apply(&self, text: &str) -> String {
        let mut out = text.to_owned();
        for (folder, stand_in) in &self.0 {
            if folder.is_empty() {
                continue;
            }
            // shortcut: exact text only (both slash styles), no case folding; Windows paths in other cases survive
            for variant in [
                folder.clone(),
                folder.replace('\\', "/"),
                folder.replace('/', "\\"),
            ] {
                out = out.replace(&variant, stand_in);
            }
        }
        out
    }
}

/// A plain sentence from a gateway message: the last non-empty line, folders replaced, at most 300 characters.
pub fn sanitize(message: &str, redact: &Redact) -> String {
    let line = message.lines().rev().map(str::trim).find(|l| !l.is_empty());
    let text = redact.apply(line.unwrap_or_default());
    match text.char_indices().nth(MAX_PROBLEM) {
        Some((end, _)) => format!("{}…", text[..end].trim_end()),
        None => text,
    }
}

pub fn engine_status(status: &Status, redact: &Redact) -> EngineStatus {
    let incompatible = status.code.as_deref() == Some("contract_mismatch");
    let state = match status.state {
        EngineState::Starting => "starting",
        EngineState::Ready => "ready",
        EngineState::Restarting => "restarting",
        EngineState::Failed if incompatible => "incompatible",
        EngineState::Failed => "failed",
        EngineState::Stopped => "unavailable",
    };
    let problem = status.message.as_ref().map(|m| Problem {
        code: status
            .code
            .clone()
            .unwrap_or_else(|| "engine_unavailable".into()),
        message: sanitize(m, redact),
    });
    EngineStatus {
        state,
        epoch: status.generation,
        protocol: PROTOCOL,
        engine_version: status.engine_version.clone(),
        contract: status.contract.clone(),
        expected_contract: bayle_gateway::CONTRACT_MAJOR,
        problem,
    }
}

/// The message for one gateway event, or None for `Lagged` (the caller sends the current status instead).
pub fn message(event: GatewayEvent, redact: &Redact) -> Option<UiMessage> {
    match event {
        GatewayEvent::Engine(status) => Some(UiMessage::Status {
            status: engine_status(&status, redact),
        }),
        GatewayEvent::Event {
            generation,
            seq,
            job_id,
            r#type,
            data,
        } => Some(UiMessage::Event {
            event: UiEvent {
                epoch: generation,
                seq,
                job_id,
                r#type,
                data,
            },
        }),
        GatewayEvent::Lagged { .. } => None,
    }
}

/// What a rejected command gives JS.
#[derive(Debug, Serialize, PartialEq)]
pub struct UiError {
    pub code: String,
    pub message: String,
    pub details: Value,
}

impl UiError {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            details: Value::Null,
        }
    }

    pub fn gateway(message: impl ToString) -> Self {
        Self::new("gateway_error", message.to_string())
    }
}

impl From<GatewayError> for UiError {
    fn from(e: GatewayError) -> Self {
        const KNOWN: [&str; 6] = [
            "engine_unavailable",
            "not_allowed",
            "bad_parameter",
            "timeout",
            "contract_mismatch",
            "engine_refused",
        ];
        let code = match e.code.strip_prefix("gateway.") {
            Some(bare) if KNOWN.contains(&bare) => bare.to_owned(),
            Some(_) => "gateway_error".to_owned(),
            None => e.code,
        };
        Self {
            code,
            message: e.message,
            details: e.details,
        }
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn redact() -> Redact {
        Redact(vec![
            (
                "C:\\Users\\me\\AppData\\Local\\Bayle\\engine".into(),
                "the install folder",
            ),
            (
                "C:\\Users\\me\\AppData\\Local\\Bayle".into(),
                "the data folder",
            ),
            ("C:\\Users\\me".into(), "~"),
        ])
    }

    fn status(state: EngineState, code: Option<&str>, message: Option<&str>) -> Status {
        Status {
            generation: 3,
            state,
            engine_version: None,
            contract: None,
            message: message.map(str::to_owned),
            code: code.map(str::to_owned),
        }
    }

    #[test]
    fn states_map_to_the_uis_words() {
        let r = redact();
        for (state, code, want) in [
            (EngineState::Starting, None, "starting"),
            (EngineState::Ready, None, "ready"),
            (EngineState::Restarting, None, "restarting"),
            (EngineState::Failed, Some("crash_loop"), "failed"),
            (EngineState::Failed, Some("engine_refused"), "failed"),
            (
                EngineState::Failed,
                Some("contract_mismatch"),
                "incompatible",
            ),
            (EngineState::Stopped, None, "unavailable"),
        ] {
            assert_eq!(engine_status(&status(state, code, None), &r).state, want);
        }
    }

    #[test]
    fn a_problem_is_one_plain_sentence() {
        let r = redact();
        let raw = "Traceback\n  File \"C:\\Users\\me\\AppData\\Local\\Bayle\\engine\\x.py\"\nOSError: cannot open C:\\Users\\me\\AppData\\Local\\Bayle\\logs and C:/Users/me/docs\n\n";
        assert_eq!(
            sanitize(raw, &r),
            "OSError: cannot open the data folder\\logs and ~/docs"
        );
        let long = "x".repeat(500);
        assert_eq!(sanitize(&long, &r).chars().count(), 301);
        let s = engine_status(
            &status(
                EngineState::Failed,
                Some("contract_mismatch"),
                Some("a\nThe engine speaks contract 2, this app 1."),
            ),
            &r,
        );
        let p = s.problem.unwrap();
        assert_eq!(
            (p.code.as_str(), p.message.as_str()),
            (
                "contract_mismatch",
                "The engine speaks contract 2, this app 1."
            )
        );
    }

    #[test]
    fn the_wire_shapes() {
        let r = redact();
        let mut ready = status(EngineState::Ready, None, None);
        ready.engine_version = Some("6.0.0".into());
        ready.contract = Some("1.2".into());
        let msg = message(GatewayEvent::Engine(ready), &r).unwrap();
        let wire = serde_json::to_value(&msg).unwrap();
        println!("{wire}");
        assert_eq!(
            wire,
            json!({"kind":"status","status":{"state":"ready","epoch":3,"protocol":1,
                "engineVersion":"6.0.0","contract":"1.2","expectedContract":"1"}})
        );
        let event = GatewayEvent::Event {
            generation: 3,
            seq: 7,
            job_id: Some("j1".into()),
            r#type: "progress".into(),
            data: json!({"done": 1, "total": 2}),
        };
        let wire = serde_json::to_value(message(event, &r).unwrap()).unwrap();
        println!("{wire}");
        assert_eq!(
            wire,
            json!({"kind":"event","event":{"epoch":3,"seq":7,"job_id":"j1","type":"progress","data":{"done":1,"total":2}}})
        );
        assert!(message(GatewayEvent::Lagged { missed: 4 }, &r).is_none());
    }

    #[test]
    fn errors_lose_the_gateway_prefix() {
        let e: UiError = GatewayError::not_allowed("x").into();
        assert_eq!(e.code, "not_allowed");
        let e: UiError = GatewayError::gateway(500, "weird", "m", Value::Null).into();
        assert_eq!(e.code, "gateway_error");
        let e: UiError = GatewayError::from_engine(
            409,
            br#"{"code":"busy","message":"Busy.","details":{"a":1}}"#,
        )
        .into();
        assert_eq!((e.code.as_str(), e.details), ("busy", json!({"a":1})));
    }
}
