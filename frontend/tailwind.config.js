/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--ui-background) / <alpha-value>)",
        foreground: "hsl(var(--ui-foreground) / <alpha-value>)",
        primary: { DEFAULT: "hsl(var(--ui-primary) / <alpha-value>)", foreground: "#ffffff" },
        secondary: {
          DEFAULT: "hsl(var(--ui-secondary) / <alpha-value>)",
          foreground: "hsl(var(--ui-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--ui-muted) / <alpha-value>)",
          foreground: "hsl(var(--ui-muted-foreground) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "hsl(var(--ui-secondary) / <alpha-value>)",
          foreground: "hsl(var(--ui-primary) / <alpha-value>)",
        },
        destructive: { DEFAULT: "#b52b20", foreground: "#ffffff" },
        border: "hsl(var(--ui-border) / <alpha-value>)",
        input: "hsl(var(--ui-border) / <alpha-value>)",
        ring: "hsl(var(--ui-ring) / <alpha-value>)",
        card: { DEFAULT: "#ffffff", foreground: "hsl(var(--ui-foreground) / <alpha-value>)" },
        popover: { DEFAULT: "#ffffff", foreground: "hsl(var(--ui-foreground) / <alpha-value>)" },
      },
    },
  },
  plugins: [require("tailwindcss-animate"), require("@tailwindcss/typography")],
};
