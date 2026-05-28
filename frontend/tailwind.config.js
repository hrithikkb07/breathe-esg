/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'DM Sans'", "system-ui", "sans-serif"],
        mono: ["'DM Mono'", "monospace"],
      },
      colors: {
        // Primary: slate-based neutral
        surface: {
          DEFAULT: "#0f1117",
          raised: "#161b27",
          border: "#232b3e",
          muted: "#1e2535",
        },
        // Accent: bright teal — used for interactive elements only
        teal: {
          400: "#2dd4bf",
          500: "#14b8a6",
          600: "#0d9488",
        },
        // Status colors
        status: {
          pending: "#64748b",
          flagged: "#f59e0b",
          approved: "#22c55e",
          rejected: "#ef4444",
        },
        // Scope colors — used consistently throughout dashboard
        scope: {
          1: "#f97316",  // orange — direct emissions
          2: "#a855f7",  // purple — purchased energy
          3: "#38bdf8",  // sky blue — value chain
        },
      },
    },
  },
  plugins: [],
};
