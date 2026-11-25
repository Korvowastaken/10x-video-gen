import path from "node:path"
import process from "node:process"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The API runs on :8765 (`python -m pipeline studio`); the dev server proxies to it.
// STUDIO_PORT moves both, so a second studio can run beside the first.
const api = `http://127.0.0.1:${process.env.STUDIO_PORT ?? "8765"}`

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { proxy: { "/api": api, "/media": api, "/refs": api } },
})
