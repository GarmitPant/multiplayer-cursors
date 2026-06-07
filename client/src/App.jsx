import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Landing from './ui/Landing.jsx';
import CanvasPage from './ui/CanvasPage.jsx';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/canvas/:code" element={<CanvasPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
