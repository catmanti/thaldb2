/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "templates/*.html",
    "templates/**/*.html",
    "clients/**/*.html",
    "users/**/*.html",
    "clients/**/*.py",
    "users/**/*.py",
    "static/js/**/*.js",
  ],
  darkMode: "class",
  theme: {
    extend: {},
  },
  plugins: [require("daisyui")],
  daisyui: {
    themes: [
      "light",
      "dark",
      "emerald",
      "corporate",
      "synthwave",
      "night",
      "dim",
      "cupcake",
      "nord",
    ],
    darkTheme: "dark",
    base: true,
    styled: true,
    utils: true,
  },
};
