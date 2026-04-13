/** @type {import("eslint").Linter.Config} */
module.exports = {
  root: true,
  extends: [
    "../../.eslintrc.js",
    "next/core-web-vitals",
  ],
  parserOptions: {
    project: "./tsconfig.json",
    tsconfigRootDir: __dirname,
  },
  rules: {
    // Next.js specific
    "@next/next/no-html-link-for-pages": "error",
    "react/jsx-no-target-blank": "error",
  },
};
