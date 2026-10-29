import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from '@tanstack/react-router';
import './styles/index.css';
import { createRuntime } from './api';
import { ApiProvider } from './data/ApiProvider';
import { router } from './router';
import { applyCachedTheme } from './app/theme';
import { Drawn, EngineGate, OutsideDesktop } from './app/shell/EngineScreens';

applyCachedTheme();
const root = createRoot(document.getElementById('root')!);

void createRuntime().then((runtime) => {
  root.render(
    <StrictMode>
      <Drawn />
      {runtime.mode === 'outside-desktop' ? <OutsideDesktop /> : (
        <ApiProvider runtime={runtime}>
          <EngineGate>
            <RouterProvider router={router} />
          </EngineGate>
        </ApiProvider>
      )}
    </StrictMode>,
  );
});
