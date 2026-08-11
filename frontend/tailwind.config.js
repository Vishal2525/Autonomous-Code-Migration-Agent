/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ["ui-monospace", "Cascadia Code", "JetBrains Mono", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
