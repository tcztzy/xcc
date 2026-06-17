# XCC GitHub Pages Site

This directory contains a standalone static landing page for XCC.

## Preview

```bash
python3 -m http.server 8765 --directory github-pages
```

Open `http://127.0.0.1:8765`.

## Deploy

This repository includes `.github/workflows/pages.yml`, which deploys this
directory to GitHub Pages when changes land on `main`. For this repository, the
expected project-site URL is:

```text
https://tcztzy.github.io/xcc/
```

Alternative deployment setups:

- In a dedicated `tcztzy.github.io` repository: copy the contents of this
  directory to that repository root.

The page uses only static HTML, CSS, and a small JavaScript file for copy
buttons. There is no build step.
