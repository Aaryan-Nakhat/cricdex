/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (space-separated RGB channels, see src/index.css) so one set of class names serves the
// dark and light themes, and opacity modifiers like `bg-accent/10` keep working.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "Cascadia Code", "Consolas", "monospace"],
      },
      colors: {
        // Pitch palette: deep night-sky base, pitch-green → teal → gold accents (sibling of EquityShastra's).
        bg: v("bg"),
        surface: v("surface"),
        card: v("card"),
        border: v("border"),
        muted: v("muted"),
        faint: v("faint"),
        fg: v("fg"),
        accent: {
          DEFAULT: v("accent"),
          dim: v("accent-dim"),
          glow: v("accent-glow"),
        },
        teal: v("teal"),
        gold: v("gold"),
        willow: v("willow"),
        ball: v("ball"),
        sky: v("sky"),
      },
      borderRadius: {
        xl: "14px",
        "2xl": "18px",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        glow: "var(--shadow-glow)",
      },
      backgroundImage: {
        grad: "var(--grad)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.35s cubic-bezier(0.16,1,0.3,1)",
      },
    },
  },
  plugins: [],
};
