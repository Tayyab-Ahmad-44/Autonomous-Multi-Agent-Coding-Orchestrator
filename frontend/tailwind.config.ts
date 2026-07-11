import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#172026",
        line: "#d7dde2",
        panel: "#f6f8fa",
        accent: "#1f7a8c",
        accentDark: "#17616f",
      },
    },
  },
  plugins: [],
};

export default config;
