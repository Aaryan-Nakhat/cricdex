import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Project page lives at https://aaryan-nakhat.github.io/cricdex/ — the
// repo name is the base path. The root portfolio at the bare domain is
// a separate repo and is untouched.
export default defineConfig({
  base: "/cricdex/",
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 1200,
  },
});
