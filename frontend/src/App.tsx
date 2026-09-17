import { Route, Routes } from 'react-router-dom';
import { CaseDetail } from './pages/CaseDetail';
import { Inbox } from './pages/Inbox';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Inbox />} />
      <Route path="/cases/:caseId" element={<CaseDetail />} />
    </Routes>
  );
}
