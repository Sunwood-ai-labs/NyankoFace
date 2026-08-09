import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..')
const errors = []
const vitepressConfig = readFileSync(join(root, '.vitepress', 'config.mts'), 'utf8')

if (!vitepressConfig.includes("logo: '/pwa-512x512.png'")) {
  errors.push('VitePress theme logo must stay unprefixed so configured base is applied exactly once')
}

const contentGroups = [
  ['articles', ['index.md', 'local-first-hub.md', 'independent-review.md', 'docker-spaces.md']],
  ['wiki', ['index.md', 'platform-map.md', 'catalog.md', 'runtime.md', 'agent-operations.md', 'glossary.md']],
  ['guide', ['getting-started.md', 'architecture.md', 'spaces.md', 'pages.md', 'visual-qa.md', 'automated-maintenance.md', 'operations.md', 'home-deployment.md', 'troubleshooting.md']],
]

function listMarkdown(directory, prefix = '') {
  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      const name = join(prefix, entry.name)
      if (entry.isDirectory()) return listMarkdown(join(directory, entry.name), name)
      return entry.isFile() && entry.name.endsWith('.md') ? [name] : []
    })
    .sort()
}

function parseFrontmatter(file) {
  const source = readFileSync(file, 'utf8')
  const match = source.match(/^---\r?\n([\s\S]*?)\r?\n---/)
  if (!match) return null
  return match[1]
}

for (const [group, expected] of contentGroups) {
  const englishDir = join(root, group)
  const japaneseDir = join(root, 'ja', group)
  const english = listMarkdown(englishDir)
  const japanese = listMarkdown(japaneseDir)

  if (JSON.stringify(english) !== JSON.stringify(japanese)) {
    errors.push(`${group}: English/Japanese page sets differ`)
  }

  for (const name of expected) {
    for (const file of [join(englishDir, name), join(japaneseDir, name)]) {
      if (!existsSync(file)) {
        errors.push(`${relative(root, file)}: missing required page`)
        continue
      }

      const frontmatter = parseFrontmatter(file)
      if (!frontmatter) {
        errors.push(`${relative(root, file)}: missing frontmatter`)
        continue
      }

      for (const key of ['title:', 'type:', 'description:', 'readingTime:', 'tags:']) {
        if (!frontmatter.includes(key)) {
          errors.push(`${relative(root, file)}: missing ${key.slice(0, -1)}`)
        }
      }
    }
  }
}

for (const locale of ['', 'ja/']) {
  const home = readFileSync(join(root, locale, 'index.md'), 'utf8')
  if (!home.includes(`<AtlasHome locale="${locale ? 'ja' : 'en'}" />`)) {
    errors.push(`${locale}index.md: AtlasHome locale is missing or incorrect`)
  }
}

if (errors.length) {
  console.error(`Documentation validation failed (${errors.length})`)
  for (const error of errors) console.error(`- ${error}`)
  process.exit(1)
}

console.log('Documentation validation passed')
console.log('- English/Japanese page parity: OK')
console.log('- Required frontmatter: OK')
console.log('- Atlas home locale wiring: OK')
console.log('- Base-safe theme logo: OK')
