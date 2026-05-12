# Clipping Club — powered by @pulp.sm

A daily browser collage game. Everyone gets the same packet of 15 public-domain image scraps each day, rotating at midnight America/New_York.

## What it does

- Daily 15-piece clipping packet
- Drag, resize, rotate, layer, front/back controls
- Mobile browser responsive layout
- Export/share generated PNG artifact
- Public-domain/open-access museum image assets

## Asset attribution

See [ATTRIBUTION.md](./ATTRIBUTION.md). Image clippings are sourced from public-domain/open-access museum collections and stored locally under `assets/real-clippings/`.

## Local testing

```bash
python3 -m http.server 8765
```

Then open `http://localhost:8765`.
