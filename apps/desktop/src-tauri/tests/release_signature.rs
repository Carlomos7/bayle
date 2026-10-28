//! A release installer verifies against the release update key exactly as the updater checks it (ADR 0016).
//! CI runs it on the signed build: BAYLE_SIGNED_FILE=<installer> cargo test -p bayle-desktop --test release_signature -- --ignored

use base64::Engine;
use minisign_verify::{PublicKey, Signature};

fn decode(b64: &str) -> String {
    String::from_utf8(
        base64::engine::general_purpose::STANDARD
            .decode(b64.trim())
            .unwrap(),
    )
    .unwrap()
}

#[test]
#[ignore = "needs a signed build: set BAYLE_SIGNED_FILE"]
fn the_signed_installer_verifies_against_the_release_key() {
    let file = std::env::var("BAYLE_SIGNED_FILE").expect("BAYLE_SIGNED_FILE");
    let config: serde_json::Value =
        serde_json::from_str(include_str!("../tauri.release.conf.json")).unwrap();
    let key = PublicKey::decode(&decode(
        config["plugins"]["updater"]["pubkey"].as_str().unwrap(),
    ))
    .unwrap();
    let signature = Signature::decode(&decode(
        &std::fs::read_to_string(format!("{file}.sig")).unwrap(),
    ))
    .unwrap();
    key.verify(&std::fs::read(&file).unwrap(), &signature, true)
        .expect("the installer's signature does not match the release key");
    let version = env!("CARGO_PKG_VERSION");
    assert!(
        signature.trusted_comment().contains(version),
        "signed for another version: {}",
        signature.trusted_comment()
    );
}
