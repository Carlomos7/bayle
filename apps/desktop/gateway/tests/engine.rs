//! ADR 0015's Phase 0 checks against the real engine (`uv run ... bayle-engine --backend`), on a scratch data folder:
//! health, Activity data, a job's ordered events and its cancel, isolation, and a kill and restart. Skipped when `uv`
//! is not on PATH.

use std::{path::PathBuf, time::Duration};

use bayle_gateway::{EngineCommand, EngineState, Gateway, GatewayEvent};
use serde_json::{Map, Value, json};
use tokio::sync::broadcast::Receiver;

fn scratch() -> PathBuf {
    let dir = std::env::temp_dir().join(format!("bayle-gateway-test-{}", std::process::id()));
    for sub in ["data", "local", "roaming", "home"] {
        std::fs::create_dir_all(dir.join(sub)).unwrap();
    }
    // a stand-in save (never a real one) so a backup job has something to copy
    let account = dir.join("roaming/EldenRing/76561198000000000");
    std::fs::create_dir_all(&account).unwrap();
    std::fs::write(account.join("ER0000.sl2"), b"not a real save").unwrap();
    dir
}

fn command(scratch: &std::path::Path) -> EngineCommand {
    let engine = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../engine");
    let s = |p: &str| scratch.join(p).to_string_lossy().into_owned();
    EngineCommand {
        program: "uv".into(),
        args: [
            "run",
            "--quiet",
            "--project",
            &engine.to_string_lossy(),
            "--extra",
            "api",
            "bayle-engine",
            "--backend",
        ]
        .map(String::from)
        .to_vec(),
        cwd: Some(engine),
        // never the real data folder: the engine moves and migrates files in it at start
        env: vec![
            ("BAYLE_DATA".into(), s("data")),
            ("LOCALAPPDATA".into(), s("local")),
            ("APPDATA".into(), s("roaming")),
            ("USERPROFILE".into(), s("home")),
            ("HOME".into(), s("home")),
        ],
        handshake_timeout: Duration::from_secs(120),
    }
}

async fn wait_for(
    rx: &mut Receiver<GatewayEvent>,
    what: &str,
    mut ok: impl FnMut(&GatewayEvent) -> bool,
) -> GatewayEvent {
    tokio::time::timeout(Duration::from_secs(120), async {
        loop {
            match rx.recv().await {
                Ok(e) if ok(&e) => return e,
                Ok(_) => {}
                Err(e) => panic!("event channel: {e}"),
            }
        }
    })
    .await
    .unwrap_or_else(|_| panic!("timed out waiting for {what}"))
}

fn ready(generation: u64) -> impl FnMut(&GatewayEvent) -> bool {
    move |e| matches!(e, GatewayEvent::Engine(s) if s.state == EngineState::Ready && s.generation == generation)
}

fn path(v: Value) -> Map<String, Value> {
    v.as_object().unwrap().clone()
}

#[tokio::test(flavor = "multi_thread")]
async fn phase_0_checks_against_the_real_engine() {
    if which("uv").is_none() {
        eprintln!("skipped: uv is not on PATH");
        return;
    }
    let dir = scratch();
    let gateway = Gateway::start(command(&dir));
    let mut rx = gateway.subscribe();
    if gateway.status().state != EngineState::Ready {
        wait_for(&mut rx, "the first engine", ready(1)).await;
    }

    // 1. health
    let health = gateway
        .call("health", Map::new(), Map::new(), None)
        .await
        .unwrap();
    assert_eq!(health["contract_version"], "1");

    // 2. Activity data
    let activity = gateway
        .call("activity", Map::new(), Map::new(), None)
        .await
        .unwrap();
    assert!(
        activity["jobs"].is_array() && activity["unseen"].is_number(),
        "{activity}"
    );

    // 5. isolation: off the allowlist, and a value that tries to reach another route
    let refused = gateway
        .call(
            "mods_delete_profile",
            Map::new(),
            Map::new(),
            Some(json!({})),
        )
        .await
        .unwrap_err();
    assert_eq!(refused.code, "gateway.not_allowed");
    let escaped = gateway
        .call(
            "get_job",
            path(json!({ "job_id": "../health" })),
            Map::new(),
            None,
        )
        .await
        .unwrap_err();
    assert_eq!(escaped.code, "gateway.bad_parameter", "{escaped}"); // refused before it reaches the engine
    let odd = gateway
        .call(
            "get_job",
            path(json!({ "job_id": "x?y=1#z" })),
            Map::new(),
            None,
        )
        .await
        .unwrap_err();
    assert_eq!(odd.status, 404, "{odd}"); // one opaque segment: the engine looked for a job of that name

    // an engine refusal comes through as the engine's Problem, unchanged
    let invalid = gateway
        .call("saves_back_up", Map::new(), Map::new(), Some(json!({})))
        .await
        .unwrap_err();
    assert_eq!(
        (invalid.status, invalid.code.as_str()),
        (422, "invalid_params"),
        "{invalid}"
    );

    // 3. a job: ordered events through to its end, and a cancel the engine answers
    let started = gateway
        .call(
            "saves_back_up",
            Map::new(),
            Map::new(),
            Some(json!({ "everything": true })),
        )
        .await;
    let job_id = match started {
        Ok(v) => v["job_id"].as_str().expect("a job id").to_owned(),
        Err(e) => panic!("the job did not start: {e}"),
    };
    let mut seqs = Vec::new();
    let end = wait_for(&mut rx, "the job's last event", |e| match e {
        GatewayEvent::Event {
            job_id: Some(id),
            seq,
            r#type,
            ..
        } if *id == job_id => {
            seqs.push(*seq);
            matches!(r#type.as_str(), "finished" | "failed" | "cancelled")
        }
        _ => false,
    })
    .await;
    assert!(
        seqs.windows(2).all(|w| w[0] < w[1]),
        "events out of order: {seqs:?}"
    );
    let cancel = gateway
        .call(
            "cancel_job",
            path(json!({ "job_id": job_id })),
            Map::new(),
            None,
        )
        .await
        .unwrap();
    assert_eq!(cancel["id"], job_id.as_str());
    eprintln!(
        "job {job_id}: events {seqs:?}, last {end:?}, after cancel {}",
        cancel["state"]
    );

    // 4. restart: the engine dies, calls fail clearly, a new generation starts, the old job is unknown
    let before = gateway.status().generation;
    gateway.kill_engine();
    wait_for(&mut rx, "the engine to stop", |e| {
        matches!(e, GatewayEvent::Engine(s) if s.generation == before && s.state != EngineState::Ready)
    })
    .await;
    let during = gateway.call("health", Map::new(), Map::new(), None).await;
    if let Err(e) = &during {
        assert_eq!(e.code, "gateway.engine_unavailable");
    }
    wait_for(&mut rx, "the restarted engine", ready(before + 1)).await;
    gateway
        .call("health", Map::new(), Map::new(), None)
        .await
        .unwrap();
    let old = gateway
        .call(
            "get_job",
            path(json!({ "job_id": job_id })),
            Map::new(),
            None,
        )
        .await
        .unwrap_err();
    assert_eq!(
        old.status, 404,
        "a restarted engine does not know the old job: {old}"
    );

    gateway.shutdown();
    wait_for(
        &mut rx,
        "the gateway to stop",
        |e| matches!(e, GatewayEvent::Engine(s) if s.state == EngineState::Stopped),
    )
    .await;
    let _ = std::fs::remove_dir_all(&dir);
}

fn which(program: &str) -> Option<PathBuf> {
    let exe = if cfg!(windows) {
        format!("{program}.exe")
    } else {
        program.to_owned()
    };
    std::env::split_paths(&std::env::var_os("PATH")?)
        .map(|d| d.join(&exe))
        .find(|p| p.is_file())
}
