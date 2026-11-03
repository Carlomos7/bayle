//! D4: an engine that keeps dying is restarted with a growing wait and then given up on, never restarted forever; one
//! that refuses to start (exit 2 or 3) is not restarted at all. A stand-in engine that exits at once, no real engine.

use std::time::{Duration, Instant};

use bayle_gateway::{EngineCommand, EngineState, Gateway, GatewayEvent, Status};

fn exits_with(code: u8) -> EngineCommand {
    let (program, args) = if cfg!(windows) {
        ("cmd", vec!["/c".to_owned(), format!("exit {code}")])
    } else {
        ("sh", vec!["-c".to_owned(), format!("exit {code}")])
    };
    EngineCommand {
        program: program.into(),
        args,
        cwd: None,
        env: vec![],
        handshake_timeout: Duration::from_secs(10),
    }
}

/// Every status until the engine is Failed or Stopped, with when it arrived.
async fn until_given_up(gateway: &Gateway) -> Vec<(Instant, Status)> {
    let mut rx = gateway.subscribe();
    let mut seen = vec![];
    tokio::time::timeout(Duration::from_secs(90), async {
        loop {
            if let Ok(GatewayEvent::Engine(s)) = rx.recv().await {
                let done = matches!(s.state, EngineState::Failed | EngineState::Stopped);
                seen.push((Instant::now(), s));
                if done {
                    return;
                }
            }
        }
    })
    .await
    .expect("the gateway never gave up on an engine that keeps dying");
    seen
}

#[tokio::test(flavor = "multi_thread")]
async fn an_engine_that_keeps_dying_is_retried_with_a_growing_wait_then_given_up() {
    let gateway = Gateway::start(exits_with(1));
    let seen = until_given_up(&gateway).await;
    let starts: Vec<Instant> = seen
        .iter()
        .filter(|(_, s)| s.state == EngineState::Starting)
        .map(|(t, _)| *t)
        .collect();
    let last = &seen.last().unwrap().1;
    assert_eq!(last.state, EngineState::Failed, "{last:?}");
    assert_eq!(last.code.as_deref(), Some("crash_loop"), "{last:?}");
    assert!(
        (4..=8).contains(&starts.len()),
        "a few tries, not forever: {}",
        starts.len()
    );
    let gaps: Vec<Duration> = starts.windows(2).map(|w| w[1] - w[0]).collect();
    // the waits double (0.5 s, 1 s, 2 s, ...); each gap also holds the stand-in's own start, so only growth is exact
    assert!(
        gaps.windows(2).all(|w| w[1] > w[0]) && *gaps.last().unwrap() > Duration::from_secs(4),
        "the wait does not grow: {gaps:?}"
    );
    gateway.shutdown(Duration::from_secs(5)).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_engine_that_refuses_to_start_is_not_restarted() {
    let gateway = Gateway::start(exits_with(3));
    let seen = until_given_up(&gateway).await;
    let starts = seen
        .iter()
        .filter(|(_, s)| s.state == EngineState::Starting)
        .count();
    let last = &seen.last().unwrap().1;
    assert_eq!(starts, 1, "{seen:?}");
    assert_eq!(last.code.as_deref(), Some("engine_refused"), "{last:?}");
    gateway.shutdown(Duration::from_secs(5)).await;
}
