import type {ReactNode} from 'react';
import {Layout} from '@astryxdesign/core/Layout';
import {VStack} from '@astryxdesign/core/VStack';
import {HStack} from '@astryxdesign/core/HStack';
import {Grid} from '@astryxdesign/core/Grid';
import {Card} from '@astryxdesign/core/Card';
import {Section} from '@astryxdesign/core/Section';
import {Text} from '@astryxdesign/core/Text';
import {Heading} from '@astryxdesign/core/Heading';
import {Button} from '@astryxdesign/core/Button';
import {Link} from '@astryxdesign/core/Link';
import {CodeBlock} from '@astryxdesign/core/CodeBlock';
import {Table} from '@astryxdesign/core/Table';
import {Mark} from './assets/Mark';
import {HeroArt} from './assets/HeroArt';
import {LocalGlyph, Ornament, RetrievalGlyph, ScopesGlyph, WritesGlyph} from './assets/Glyphs';
import {BarList} from './components/BarList';
import {LIVE_BY_KIND, LIVE_TOTAL, LOCOMO, LONGMEMEVAL, PILLARS, REPO, SNIPPETS} from './content';

const GLYPHS: Record<string, ReactNode> = {
  writes: <WritesGlyph />,
  scopes: <ScopesGlyph />,
  retrieval: <RetrievalGlyph />,
  local: <LocalGlyph />,
};

function SectionHead({id, title, children}: {id: string; title: string; children: ReactNode}) {
  return (
    <VStack gap={3} hAlign="center" id={id}>
      <Ornament />
      <Heading level={2} type="display-3" justify="center" textWrap="balance">
        {title}
      </Heading>
      <Text type="large" color="secondary" justify="center" textWrap="balance">
        {children}
      </Text>
    </VStack>
  );
}

function Header() {
  return (
    <HStack hAlign="between" vAlign="center" paddingBlock={3} paddingInline={4} gap={4}>
      <HStack gap={3} vAlign="center">
        <Mark height={40} title="Teresis" />
        <Text type="large" weight="semibold">
          Teresis
        </Text>
      </HStack>
      <HStack gap={1} vAlign="center">
        <Button label="Results" variant="ghost" size="sm" href="#results" />
        <Button label="Install" variant="ghost" size="sm" href="#install" />
        <Button label="Source" variant="secondary" size="sm" href={REPO} />
      </HStack>
    </HStack>
  );
}

function Hero() {
  return (
    <VStack gap={8} hAlign="center" paddingBlockStart={6}>
      <VStack gap={4} hAlign="center">
        <Text type="label" color="accent" weight="semibold">
          τήρησις · faithful keeping
        </Text>
        <Heading level={1} type="display-1" justify="center" textWrap="balance">
          Local memory for AI agents
        </Heading>
        <Text type="large" color="secondary" justify="center" textWrap="balance">
          One SQLite file, no dependencies. A Hermes memory provider, an MCP server, a local HTTP API, a CLI and a
          Python API, all sharing the same store.
        </Text>
      </VStack>
      <HStack gap={3}>
        <Button label="See the results" variant="primary" size="lg" href="#results" />
        <Button label="Install in Hermes" variant="secondary" size="lg" href="#install" />
      </HStack>
      <VStack maxWidth={680} width="100%">
        <CodeBlock code={SNIPPETS.hermes} language="bash" title="Hermes" />
      </VStack>
      <VStack width="100%">
        <HeroArt />
      </VStack>
    </VStack>
  );
}

function ResultCard({title, subtitle, children}: {title: string; subtitle: string; children: ReactNode}) {
  return (
    <Card padding={6}>
      <VStack gap={5}>
        <VStack gap={1}>
          <Heading level={3} weight="semibold">
            {title}
          </Heading>
          <Text type="supporting" color="secondary">
            {subtitle}
          </Text>
        </VStack>
        {children}
      </VStack>
    </Card>
  );
}

function Results() {
  return (
    <VStack gap={8}>
      <SectionHead id="results" title="Measured, not described">
        Two retrieval benchmarks with the same defaults, and a live agent answering from memory.
      </SectionHead>
      <ResultCard title="A live Hermes agent" subtitle="200 facts told in earlier sessions, 100 questions asked in fresh ones. Questions answered correctly.">
        <Grid columns={{minWidth: 420, repeat: 'fit'}} gap={8} align="center">
          <BarList rows={LIVE_TOTAL} max={100} metric="correct" />
          <Table
            density="compact"
            idKey="kind"
            data={LIVE_BY_KIND}
            columns={[
              {key: 'kind', header: 'Question type'},
              {key: 'teresis', header: 'Teresis', align: 'end', renderCell: (r) => `${r.teresis}/${r.asked}`},
              {key: 'stock', header: 'Stock Hermes', align: 'end', renderCell: (r) => `${r.stock}/${r.asked}`},
            ]}
          />
        </Grid>
      </ResultCard>
      <Grid columns={{minWidth: 440, repeat: 'fit'}} gap={6}>
        <ResultCard title="LoCoMo" subtitle="1,536 questions over 10 long conversations. Share of questions with the exact evidence turn in the top 5 (recall_any@5).">
          <BarList rows={LOCOMO} max={1} metric="recall_any@5" />
        </ResultCard>
        <ResultCard title="LongMemEval-S" subtitle="100 held-out questions over ~50-session histories. Ranking quality of the evidence sessions (NDCG@10).">
          <BarList rows={LONGMEMEVAL} max={1} metric="NDCG@10" />
        </ResultCard>
      </Grid>
      <VStack gap={2} hAlign="center">
        <Text type="supporting" color="secondary" justify="center" textWrap="balance">
          The live run is one pass per arm on gpt-6.1-terra, medium reasoning, fast mode off. A 30-fact version tied: the gap
          appears once memory outgrows Hermes' built-in 3,200-character file. mem0 ran with infer=False and without its
          optional BM25 and spaCy extras. The two benchmarks score retrieval, not answer generation.
        </Text>
        <Link href={REPO} isExternalLink label="Methodology and raw results in the repository">
          Methodology and raw results
        </Link>
      </VStack>
    </VStack>
  );
}

function How() {
  return (
    <VStack gap={8}>
      <SectionHead id="how" title="Built around the write path">
        Agents write constantly, repeat themselves, and change their minds. Teresis is designed for that as much as for
        search.
      </SectionHead>
      <Grid columns={{minWidth: 480, repeat: 'fit'}} gap={6}>
        {PILLARS.map((p) => (
          <Card key={p.key} padding={6}>
            <VStack gap={4}>
              {GLYPHS[p.key]}
              <Heading level={3} weight="semibold">
                {p.title}
              </Heading>
              <Text color="secondary">{p.body}</Text>
            </VStack>
          </Card>
        ))}
      </Grid>
    </VStack>
  );
}

function Install() {
  return (
    <VStack gap={8}>
      <SectionHead id="install" title="One store, every client">
        Hermes, MCP clients, plain HTTP and Python all read and write the same file.
      </SectionHead>
      <Grid columns={{minWidth: 520, repeat: 'fit'}} gap={6}>
        <CodeBlock code={SNIPPETS.hermes} language="bash" title="Hermes Agent" width="100%" isWrapped />
        <CodeBlock code={SNIPPETS.mcp} language="bash" title="MCP (Claude Code, Codex, Cursor)" width="100%" isWrapped />
        <CodeBlock code={SNIPPETS.http} language="bash" title="HTTP" width="100%" isWrapped />
        <CodeBlock code={SNIPPETS.python} language="python" title="Python" width="100%" isWrapped />
      </Grid>
    </VStack>
  );
}

function Footer() {
  return (
    <VStack gap={3} hAlign="center" paddingBlock={8} paddingInline={4}>
      <Ornament />
      <Text color="secondary" justify="center">
        Teresis · τήρησις, faithful keeping
      </Text>
      <Link href={REPO} isExternalLink label="Teresis source repository">
        Source
      </Link>
    </VStack>
  );
}

export function App() {
  return (
    <Layout
      height="auto"
      contentWidth={1120}
      padding={4}
      header={<Header />}
      content={
        <VStack gap={10} paddingBlockEnd={6} paddingInline={4}>
          <Hero />
          <Results />
          <How />
          <Install />
        </VStack>
      }
      footer={<Footer />}
    />
  );
}
