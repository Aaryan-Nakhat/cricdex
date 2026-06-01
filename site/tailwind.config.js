/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        // Pitch — the app's palette. Deep slate base, willow-green accent.
        bg: "#0a0e14",
        surface: "#10151f",
        card: "#141b27",
        border: "#1e2836",
        muted: "#8a97a8",
        fg: "#e6edf3",
        accent: {
          DEFAULT: "#34d399",
          dim: "#10b981",
          glow: "#6ee7b7",
        },
        willow: "#a3e635",
        ball: "#f43f5e",
      },
      boxShadow: {
        card: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.6)",
        glow: "0 0 0 1px rgba(52,211,153,0.25), 0 0 32px -8px rgba(52,211,153,0.35)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.35s cubic-bezier(0.16,1,0.3,1)",
        shimmer: "shimmer 1.5s infinite",
      },
    },
  },
  plugins: [],
};
