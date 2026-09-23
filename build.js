process.env.BROWSERSLIST_IGNORE_OLD_DATA = "true";
process.env.BROWSERSLIST_DISABLE_WARNINGS = "1";

const fs = require("fs");
const path = require("path");
const postcss = require("postcss");
const tailwindcss = require("tailwindcss");

async function buildCSS() {
  const inputPath = path.resolve(__dirname, "static/css/input.css");
  const outputPath = path.resolve(__dirname, "static/css/app.css");
  const configPath = path.resolve(__dirname, "tailwind.config.js");

  const css = fs.readFileSync(inputPath, "utf8");

  const result = await postcss([
    tailwindcss(configPath),
  ]).process(css, { from: inputPath, to: outputPath });

  fs.writeFileSync(outputPath, result.css);
  console.log(`SUCCESS! Generated app.css size: ${(result.css.length / 1024).toFixed(1)} KB`);
}

buildCSS().catch((err) => {
  console.error("Build failed:", err);
  process.exit(1);
});
