import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    if (import.meta.env.DEV) {
      console.error('Uncaught UI error:', error, info);
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="mx-auto max-w-xl p-8 text-center" role="alert">
          <h1 className="text-lg font-bold text-[#172033]">Something went wrong</h1>
          <p className="mt-2 text-sm text-[#667085]">
            The page hit an unexpected error. Your session is intact — go back and retry.
            {import.meta.env.DEV && this.state.error
              ? ` (${String(this.state.error.message || this.state.error).slice(0, 200)})`
              : ''}
          </p>
          <div className="mt-4 flex justify-center gap-2">
            <button type="button" onClick={() => window.history.back()} className="gov-btn gov-btn-secondary">
              Go back
            </button>
            <button type="button" onClick={() => { this.setState({ hasError: false, error: null }); window.location.href = '/'; }} className="gov-btn gov-btn-primary">
              Overview
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
