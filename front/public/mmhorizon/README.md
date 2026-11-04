# MMhorizon core, compiled to WebAssembly

The Horizon page (`/horizon`) analyses a 360-degree panorama in the browser
with these two files; the photo is not uploaded.

- Source: [mmedia-fr/mmhorizon](https://github.com/mmedia-fr/mmhorizon),
  GPL-3.0-or-later, release
  [v0.1.3](https://github.com/mmedia-fr/mmhorizon/releases/tag/v0.1.3), commit
  `48a994f` (`wasm/` crate): the two files of `mmhorizon-noyau-wasm-0.1.3.zip`.
- Interface: `docs/WASM.md` in that repository.
- Built with:

  ```sh
  cargo build --manifest-path wasm/Cargo.toml --release --locked --target wasm32-unknown-unknown
  wasm-bindgen --target web --out-dir dist/wasm wasm/target/wasm32-unknown-unknown/release/mmhorizon_wasm.wasm
  ```

Do not edit them: rebuild from the source, or take the `mmhorizon-noyau-wasm`
artifact of its CI, and replace both files together.

| File | SHA-256 |
|---|---|
| `mmhorizon_wasm.js` | `0effd8c0990e4d90700d677e321fd654a9b3c8e68230b8a646e6dd5d4a80e1f4` |
| `mmhorizon_wasm_bg.wasm` | `66275b9b5dcf751cc8eef137cef1ca36394b1c93ff6f523d08f83f817f951876` |
