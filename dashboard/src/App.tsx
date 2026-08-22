import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Pipeline } from './pages/Pipeline'
import { Decisions } from './pages/Decisions'
import { Ledger } from './pages/Ledger'
import { Guardrails } from './pages/Guardrails'
import { Metrics } from './pages/Metrics'

function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/pipeline" replace />} />
        <Route path="/pipeline" element={<Pipeline />} />
        <Route path="/decisions" element={<Decisions />} />
        <Route path="/ledger" element={<Ledger />} />
        <Route path="/guardrails" element={<Guardrails />} />
        <Route path="/metrics" element={<Metrics />} />
        <Route path="*" element={<Navigate to="/pipeline" replace />} />
      </Route>
    </Routes>
  )
}

export default App
