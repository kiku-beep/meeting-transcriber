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
        <div className="error-boundary" role="alert">
          <h1 className="error-boundary__title">エラーが発生しました</h1>
          <p className="error-boundary__message">{this.state.error?.message}</p>
          <button
            onClick={() => window.location.reload()}
            className="error-boundary__reload"
          >
            再読み込み
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
