import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import path from "node:path";

const CSP_HASHES = "'csp-inline-script-hashes'";
const CSP_META = /<meta\s+http-equiv="Content-Security-Policy"[^>]*>\s*/i;

// The Content-Security-Policy lives in index.html as a <meta> tag (GitHub Pages can't send headers).
// - build: every inline <script> in the final HTML is hashed and the hashes replace the
//   'csp-inline-script-hashes' placeholder, so the policy allows exactly those scripts and no others
//   (hashing the built file means line endings or a later edit of the theme script can't break it).
// - dev: the meta tag is removed, since Vite's dev server injects its own inline scripts and HMR socket.
function contentSecurityPolicy(): Plugin {
  return {
    name: "cricdesk-csp",
    transformIndexHtml: {
      order: "post",
      handler(html, ctx) {
        if (ctx.server) return html.replace(CSP_META, "");
        if (!html.includes(CSP_HASHES)) {
          throw new Error("index.html: the CSP meta tag (with its hash placeholder) is missing");
        }
        // The browser hashes the script text after HTML parsing, which turns CRLF / CR into LF.
        const hashes = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(
          (m) => {
            const text = m[1].replace(/\r\n?/g, "\n");
            return `'sha256-${createHash("sha256").update(text, "utf8").digest("base64")}'`;
          },
        );
        return html.replace(CSP_HASHES, hashes.join(" "));
      },
    },
  };
}

// Project page lives at https://aaryan-nakhat.github.io/cricdesk/ — the
// repo name is the base path. The root portfolio at the bare domain is
// a separate repo and is untouched.
export default defineConfig({
  base: "/cricdesk/",
  plugins: [react(), contentSecurityPolicy()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 1200,
  },
});
