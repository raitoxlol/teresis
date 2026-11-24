import {Bookplate, TitlePage, TryTablePage, TryTerminalPage, ScopePage, MethodPage, HermesPage, ClientsPage} from './spreads/a';
import {LiveBenchPage, EvaluationPage, InstallPage, InstallCommandPage, QuestionsPage, ClosingPage, ColophonPage, BackCoverPage} from './spreads/b';

export const PAGES = [
  {id: 'bookplate', title: 'Kept for you', Content: Bookplate, endpaper: true},
  {id: 'title-page', title: 'Teresis', Content: TitlePage},
  {id: 'try', title: 'Try it', Content: TryTablePage},
  {id: 'try-terminal', title: 'Try it', Content: TryTerminalPage},
  {id: 'how', title: 'Method', Content: ScopePage},
  {id: 'method-details', title: 'Method', Content: MethodPage},
  {id: 'works-with', title: 'Works with', Content: HermesPage},
  {id: 'clients', title: 'Works with', Content: ClientsPage},
  {id: 'benchmarks', title: 'Benchmarks', Content: LiveBenchPage, print: 'benchmarks.webp'},
  {id: 'evaluation', title: 'Benchmarks', Content: EvaluationPage, print: 'evaluation.webp', variants: ['longmemeval.webp', 'locomo.webp']},
  {id: 'install', title: 'Install', Content: InstallPage},
  {id: 'install-command', title: 'Install', Content: InstallCommandPage},
  {id: 'questions', title: 'Questions', Content: QuestionsPage},
  {id: 'contact', title: 'Keep the file on your machine', Content: ClosingPage},
  {id: 'colophon', title: 'Colophon', Content: ColophonPage},
  {id: 'back-cover', title: 'Inside back cover', Content: BackCoverPage, endpaper: true},
];
