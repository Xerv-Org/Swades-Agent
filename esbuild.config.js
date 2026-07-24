import esbuild from 'esbuild';

esbuild.build({
  entryPoints: ['./src/extension.js'],
  bundle: true,
  outfile: './dist/extension.js',
  external: ['vscode'],
  format: 'cjs',
  platform: 'node',
  minify: false,
  sourcemap: true,
}).catch((err) => {
  console.error('esbuild compilation failed:', err);
  process.exit(1);
});
