import { Component, ErrorInfo, ReactNode } from "react";

interface Props { children: ReactNode; }
interface State { hasError: boolean; error: Error | null; }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="h-screen flex flex-col items-center justify-center bg-slate-900 text-white gap-4">
          <h1 className="text-xl font-bold text-red-400">エラーが発生しました</h1>
          <p className="text-slate-400 text-sm">{this.state.error?.message}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm"
          >
            再読み込み
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
