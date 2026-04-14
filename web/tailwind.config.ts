import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          DEFAULT: "#0D1B3E",
          50: "#E8EBF2",
          100: "#C5CCE0",
          200: "#9EAACB",
          300: "#7788B6",
          400: "#5066A1",
          500: "#2A448C",
          600: "#1E3267",
          700: "#0D1B3E",
          800: "#091229",
          900: "#050A15",
        },
        gold: {
          DEFAULT: "#C9A84C",
          50: "#FCF8EE",
          100: "#F5ECCD",
          200: "#EDDFAB",
          300: "#E2CE7D",
          400: "#D6BC62",
          500: "#C9A84C",
          600: "#B0903A",
          700: "#8A712E",
          800: "#655222",
          900: "#403416",
        },
      },
    },
  },
  plugins: [],
};

export default config;
