import { Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { useApp } from './context/AppContext';
import { EconomicsPage, FieldHistoryPage, MarketPage, PlanningPage, ResearchPage, SchemesPage, AlertsPage } from './pages/AnalysisPages';
import { ChatPage } from './pages/ChatPage';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import { ScanPage, SoilPage, WeatherPage } from './pages/PerceptionPages';

function ProtectedLayout() {
  const { session } = useApp();
  return session?.access_token ? <Outlet/> : <Navigate to="/login" replace/>;
}

function LoginRoute() {
  const { session } = useApp();
  return session?.access_token ? <Navigate to="/" replace/> : <LoginPage/>;
}

export function App() {
  return <Routes>
    <Route path="/login" element={<LoginRoute/>}/>
    <Route element={<ProtectedLayout/>}>
      <Route element={<AppShell/>}>
        <Route index element={<OverviewPage/>}/>
        <Route path="perception/crop" element={<ScanPage kind="crop"/>}/>
        <Route path="perception/livestock" element={<ScanPage kind="livestock"/>}/>
        <Route path="perception/weather" element={<WeatherPage/>}/>
        <Route path="perception/soil" element={<SoilPage/>}/>
        <Route path="analysis/history" element={<FieldHistoryPage/>}/>
        <Route path="analysis/economics" element={<EconomicsPage/>}/>
        <Route path="analysis/market" element={<MarketPage/>}/>
        <Route path="intelligence/chat" element={<ChatPage/>}/>
        <Route path="intelligence/research" element={<ResearchPage/>}/>
        <Route path="action/planning" element={<PlanningPage/>}/>
        <Route path="action/schemes" element={<SchemesPage/>}/>
        <Route path="action/alerts" element={<AlertsPage/>}/>
      </Route>
    </Route>
    <Route path="*" element={<Navigate to="/" replace/>}/>
  </Routes>;
}
