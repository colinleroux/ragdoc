import { defineConfig } from "vite";

export default defineConfig({
  build: {
    manifest: "manifest.json",
    outDir: "app/static/vite",
    assetsDir: "assets",
    rollupOptions: {
      input: "src/main.js"
    }
  }
});
