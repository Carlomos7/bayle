//! Turns allowlist.txt and the engine's OpenAPI snapshot into the operation table the gateway checks every call
//! against (ADR 0015). An allowlisted id the contract does not have fails the build, so contract drift cannot ship.

use std::{env, fs, path::PathBuf};

use serde_json::Value;

fn main() {
    let here = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let spec_path = env::var_os("BAYLE_OPENAPI")
        .map(PathBuf::from)
        .unwrap_or_else(|| here.join("../../../docs/api/openapi.json"));
    let allow_path = here.join("allowlist.txt");
    println!("cargo:rerun-if-changed={}", spec_path.display());
    println!("cargo:rerun-if-changed={}", allow_path.display());
    println!("cargo:rerun-if-env-changed=BAYLE_OPENAPI");

    let spec: Value =
        serde_json::from_str(&fs::read_to_string(&spec_path).expect("read the OpenAPI snapshot"))
            .expect("parse the OpenAPI snapshot");
    let allow = fs::read_to_string(&allow_path).expect("read allowlist.txt");

    let mut out = String::from("pub static OPERATIONS: &[Operation] = &[\n");
    for id in allow
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
    {
        let (path, method, op, path_item) = find(&spec, id).unwrap_or_else(|| {
            panic!("allowlist.txt names `{id}`, which docs/api/openapi.json does not have")
        });
        let mut path_params = Vec::new();
        let mut query_params = Vec::new();
        for p in params(path_item).chain(params(op)) {
            let name = p["name"].as_str().unwrap().to_string();
            match p["in"].as_str() {
                Some("path") => path_params.push(name),
                Some("query") => query_params.push(name),
                _ => {} // headers and cookies are the gateway's, never the caller's
            }
        }
        for name in path
            .split('/')
            .filter_map(|s| s.strip_prefix('{').and_then(|s| s.strip_suffix('}')))
        {
            assert!(
                path_params.contains(&name.to_string()),
                "`{id}`: path parameter {name} is not declared"
            );
        }
        out += &format!(
            "    Operation {{ id: {id:?}, method: {method:?}, path: {path:?}, path_params: &{path_params:?}, \
             query_params: &{query_params:?}, has_body: {} }},\n",
            op.get("requestBody").is_some()
        );
    }
    out += "];\n";
    let contract = spec["info"]["version"]
        .as_str()
        .expect("info.version is the contract major");
    out += &format!("pub const CONTRACT_MAJOR: &str = {contract:?};\n");
    fs::write(
        PathBuf::from(env::var("OUT_DIR").unwrap()).join("operations.rs"),
        out,
    )
    .unwrap();
}

fn find<'a>(spec: &'a Value, id: &str) -> Option<(&'a str, String, &'a Value, &'a Value)> {
    spec["paths"].as_object()?.iter().find_map(|(path, item)| {
        item.as_object()?.iter().find_map(|(method, op)| {
            (op.get("operationId")?.as_str()? == id)
                .then(|| (path.as_str(), method.to_uppercase(), op, item))
        })
    })
}

fn params(v: &Value) -> impl Iterator<Item = &Value> {
    v.get("parameters")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
}
