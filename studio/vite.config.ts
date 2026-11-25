import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The API runs on :8765 (`python -m pipeline studio`); the dev server proxies to it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { proxy: { "/api": "http://127.0.0.1:8765", "/media": "http://127.0.0.1:8765", "/refs": "http://127.0.0.1:8765" } },
})
