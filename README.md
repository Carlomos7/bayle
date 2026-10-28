# updates

Bayle's update manifests, served by GitHub Pages:

- Stable: `https://carlomos7.github.io/bayle/updates/stable.json`
- Beta: `https://carlomos7.github.io/bayle/updates/beta.json`

`site/` is published as is on every push (`.github/workflows/pages.yml`), after a check that each manifest
points at a signed build on this repo's releases. The channels are separate files; a beta never goes in
`stable.json`. Add or change a manifest only for a signed, verified build the owner approved.
