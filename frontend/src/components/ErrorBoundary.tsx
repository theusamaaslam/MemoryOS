import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught app error:", error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center p-8 text-center" style={{ height: "100vh", backgroundColor: "var(--bg-base)" }}>
          <div className="card glass-panel" style={{ maxWidth: "500px", padding: "3rem" }}>
            <div style={{ display: "flex", justifyContent: "center" }}>
               <AlertTriangle className="text-danger mb-4" size={56} />
            </div>
            <h2>Application Error</h2>
            <p className="text-secondary mt-2 mb-6 text-sm">
              {this.state.error?.message || "An unexpected error occurred while rendering the UI."}
            </p>
            <button className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload Session
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
