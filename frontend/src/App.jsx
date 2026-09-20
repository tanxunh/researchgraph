import { Route, Routes } from 'react-router-dom';
import AppShell from './components/AppShell';
import Overview from './pages/Overview';
import { NotFound } from './pages/PageShell';
import Library from './pages/Library';
import Jobs from './pages/Jobs';
import DocumentDetail from './pages/DocumentDetail';
import SearchWorkspace from './pages/SearchWorkspace';
import AskWorkspace from './pages/AskWorkspace';
import ResearchWorkspace from './pages/ResearchWorkspace';
export default function App() {
  return <Routes><Route element={<AppShell />}><Route index element={<Overview />} />
    <Route path="search" element={<SearchWorkspace />} />
    <Route path="ask" element={<AskWorkspace />} />
    <Route path="research" element={<ResearchWorkspace />} />
    <Route path="library" element={<Library />} /><Route path="jobs" element={<Jobs />} /><Route path="library/:documentId" element={<DocumentDetail />} /><Route path="*" element={<NotFound />} />
  </Route></Routes>;
}
