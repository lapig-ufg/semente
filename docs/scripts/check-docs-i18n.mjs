#!/usr/bin/env node
// Verifica se as versões em inglês (docs/) e português (docs/pt/) estão em sincronia.
//   1. Toda página .md em inglês precisa ter par em docs/pt/ (e vice-versa).
//   2. Com --base <ref>: se um idioma foi alterado, o outro também precisa ser.
// Uso: node scripts/check-docs-i18n.mjs [--base origin/main]
import { execSync } from 'node:child_process'
import { readdirSync, existsSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

const docsDir = new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const IGNORE = new Set(['node_modules', '.vitepress', 'public', 'pt'])

function walk(dir, skipTop = false) {
  const out = []
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (skipTop && IGNORE.has(e.name)) continue
    if (e.name === 'node_modules' || e.name === '.vitepress') continue
    const p = join(dir, e.name)
    if (e.isDirectory()) out.push(...walk(p))
    else if (e.name.endsWith('.md')) out.push(p)
  }
  return out
}

const rel = (p, root) => relative(root, p).split(sep).join('/')
const en = walk(docsDir, true).map((p) => rel(p, docsDir))
const ptRoot = join(docsDir, 'pt')
const pt = existsSync(ptRoot) ? walk(ptRoot).map((p) => rel(p, ptRoot)) : []

const errors = []
for (const f of en) if (!pt.includes(f)) errors.push(`Falta a tradução PT: docs/pt/${f}`)
for (const f of pt) if (!en.includes(f)) errors.push(`Falta a versão EN: docs/${f}`)

const baseIdx = process.argv.indexOf('--base')
if (baseIdx !== -1) {
  const base = process.argv[baseIdx + 1]
  // Páginas novas (A) já são cobertas pela checagem de pares acima; só comparamos as modificadas.
  const changed = execSync(`git diff --name-only --diff-filter=M ${base}...HEAD -- docs`, { encoding: 'utf8' })
    .split('\n')
    .filter((f) => f.endsWith('.md'))
  const set = new Set(changed)
  for (const f of changed) {
    const isPt = f.startsWith('docs/pt/')
    const name = isPt ? f.slice('docs/pt/'.length) : f.slice('docs/'.length)
    const other = isPt ? `docs/${name}` : `docs/pt/${name}`
    if (!set.has(other)) {
      errors.push(`${f} foi alterado, mas ${other} não — atualize o outro idioma.`)
    }
  }
}

if (errors.length) {
  console.error('❌ Documentação fora de sincronia entre EN e PT:\n')
  for (const e of [...new Set(errors)]) console.error(`  - ${e}`)
  process.exit(1)
}
console.log('✓ Documentação EN/PT em sincronia.')
