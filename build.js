const fs = require("fs");
const postcss = require("postcss");
const tailwindcss = require("tailwindcss");
const autoprefixer = require("autoprefixer");

async function buildCSS() {
  fs.writeFileSync("status.txt", "Reading input.css...\n");
  const css = fs.readFileSync("./static/css/input.css", "utf8");

  fs.appendFileSync("status.txt", "Compiling PostCSS...\n");
  const result = await postcss([
    tailwindcss("./tailwind.config.js"),
    autoprefixer,
  ]).process(css, { from: "./static/css/input.css", to: "./static/css/output.css" });

  fs.writeFileSync("./static/css/output.css", result.css);
  fs.appendFileSync("status.txt", `DONE! Output CSS size: ${(result.css.length / 1024).toFixed(1)} KB\n`);
}

buildCSS().catch((err) => {
  fs.appendFileSync("status.txt", `ERROR: ${err.stack}\n`);
  process.exit(1);
});
