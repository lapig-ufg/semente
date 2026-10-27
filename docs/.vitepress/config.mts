import { defineConfig, type DefaultTheme } from 'vitepress'
import llmstxt from 'vitepress-plugin-llms'

// Project pages live under /semente/ — assets 404 without this base.
// cleanUrls: false (default) because GitHub Pages has no fallback rewrite.
const base = '/semente/'

// English lives at the site root; Portuguese lives under /pt/.
function nav(prefix: string, t: Record<string, string>): DefaultTheme.NavItem[] {
  return [
    { text: t.guide, link: `${prefix}/guide/getting-started` },
    { text: t.deployment, link: `${prefix}/deployment/toy-app` },
    { text: t.architecture, link: `${prefix}/architecture/` },
    { text: t.showcase, link: `${prefix}/showcase/pasto-legal` },
  ]
}

function sidebar(prefix: string, t: Record<string, string>): DefaultTheme.Sidebar {
  return {
    [`${prefix}/guide/`]: [
      {
        text: t.guide,
        items: [
          { text: t.gettingStarted, link: `${prefix}/guide/getting-started` },
          { text: t.domain, link: `${prefix}/guide/domain` },
          { text: t.domainApi, link: `${prefix}/guide/domain-api` },
          { text: t.manifest, link: `${prefix}/guide/manifest` },
          { text: t.guardrails, link: `${prefix}/guide/guardrails` },
          { text: t.cli, link: `${prefix}/guide/cli` },
          { text: t.feedback, link: `${prefix}/guide/feedback` },
          { text: t.prompts, link: `${prefix}/guide/prompts` },
          { text: t.channels, link: `${prefix}/guide/channels` },
          { text: t.engines, link: `${prefix}/guide/engines` },
        ],
      },
    ],
    [`${prefix}/deployment/`]: [
      {
        text: t.deployment,
        items: [{ text: t.toyApp, link: `${prefix}/deployment/toy-app` }],
      },
    ],
    [`${prefix}/architecture/`]: [
      {
        text: t.architecture,
        items: [{ text: t.overview, link: `${prefix}/architecture/` }],
      },
    ],
    [`${prefix}/showcase/`]: [
      {
        text: t.showcase,
        items: [
          { text: 'Pasto Legal', link: `${prefix}/showcase/pasto-legal` },
          { text: t.groot, link: `${prefix}/showcase/groot` },
        ],
      },
    ],
  }
}

const en = {
  guide: 'Guide',
  deployment: 'Deployment',
  architecture: 'Architecture',
  showcase: 'Showcase',
  gettingStarted: 'Getting Started',
  domain: 'The Domain',
  domainApi: 'Domain API',
  manifest: 'Manifest Reference',
  guardrails: 'Guardrails',
  cli: 'CLI Reference',
  feedback: 'Feedback & Fine-Tuning',
  prompts: 'Prompts & i18n',
  channels: 'Channels',
  engines: 'Engines',
  toyApp: 'Toy App',
  overview: 'Overview',
  groot: 'Groot (Docs AI)',
}

const pt = {
  guide: 'Guia',
  deployment: 'Implantação',
  architecture: 'Arquitetura',
  showcase: 'Vitrine',
  gettingStarted: 'Primeiros Passos',
  domain: 'O Domínio',
  domainApi: 'API do Domínio',
  manifest: 'Referência do Manifesto',
  guardrails: 'Guardrails',
  cli: 'Referência da CLI',
  feedback: 'Feedback e Fine-Tuning',
  prompts: 'Prompts e i18n',
  channels: 'Canais',
  engines: 'Engines',
  toyApp: 'App de Exemplo',
  overview: 'Visão Geral',
  groot: 'Groot (IA da Documentação)',
}

export default defineConfig({
  title: 'Semente',
  description: 'Multi-agent AI chat framework for land use and agriculture',
  base,
  // First visit: open the Portuguese pages when the browser prefers pt.
  // After that the language of the page being viewed is remembered, so the
  // language switcher always wins over browser detection.
  head: [
    [
      'script',
      {},
      `(function(){try{
var b=${JSON.stringify(base)},p=location.pathname;
if(p.indexOf(b)!==0)return;
var rest=p.slice(b.length),isPt=rest==='pt'||rest.indexOf('pt/')===0,k='semente-lang',s=localStorage.getItem(k);
if(!s){
var l=(navigator.languages&&navigator.languages[0])||navigator.language||'en';
if(l.toLowerCase().indexOf('pt')===0&&!isPt){location.replace(b+'pt/'+rest+location.search+location.hash);return;}
}
localStorage.setItem(k,isPt?'pt':'en');
}catch(e){}})();`,
    ],
  ],
  // Machine-readable docs for AI consumers: /llms.txt, /llms-full.txt and a
  // plain-Markdown copy of every page (https://llmstxt.org).
  vite: {
    plugins: [
      llmstxt({
        domain: 'https://lapig-ufg.github.io',
        title: 'Semente',
        description:
          'Multi-agent AI chat framework for land use and agriculture. English docs at the root, Portuguese (pt-BR) under /pt/.',
        details:
          'Every page exists in English and in Portuguese (URLs starting with /pt/). Prefer the English pages unless the user writes in Portuguese.',
      }),
    ],
  },
  locales: {
    root: {
      label: 'English',
      lang: 'en-US',
      themeConfig: {
        nav: nav('', en),
        sidebar: sidebar('', en),
        footer: {
          message: 'Extracted from Pasto Legal (LAPIG/UFG)',
          copyright: 'GPL-3.0-or-later',
        },
      },
    },
    pt: {
      label: 'Português',
      lang: 'pt-BR',
      link: '/pt/',
      description: 'Framework de chat com IA multiagente para uso da terra e agropecuária',
      themeConfig: {
        nav: nav('/pt', pt),
        sidebar: sidebar('/pt', pt),
        footer: {
          message: 'Extraído do Pasto Legal (LAPIG/UFG)',
          copyright: 'GPL-3.0-or-later',
        },
        outline: { label: 'Nesta página' },
        docFooter: { prev: 'Anterior', next: 'Próximo' },
        darkModeSwitchLabel: 'Aparência',
        sidebarMenuLabel: 'Menu',
        returnToTopLabel: 'Voltar ao topo',
        langMenuLabel: 'Mudar idioma',
        lightModeSwitchTitle: 'Mudar para tema claro',
        darkModeSwitchTitle: 'Mudar para tema escuro',
      },
    },
  },
  themeConfig: {
    logo: '🌱',
    socialLinks: [{ icon: 'github', link: 'https://github.com/lapig-ufg/semente' }],
  },
})