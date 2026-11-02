/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#172033",
        mist: "#f4f7fb",
        teal: "#0d9488",
      },
      boxShadow: {
        card: "0 12px 40px rgba(25, 43, 73, 0.08)",
      },
    },
  },
  plugins: [],
};
