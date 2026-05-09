# 📊 KiBot Support: Web Dashboard & Monitoring

Web-based visualization and real-time monitoring tools for the KiBot ecosystem.

## Responsibility
- **Dashboarding**: Providing a browser-based view of trading activity, signal history, and mesh health.
- **Visual Analytics**: Displaying PnL curves, signal heatmaps, and node connectivity status.
- **Remote Oversight**: Allowing secure monitoring of the Batam node and the Trinity cluster from any authenticated browser.

## Key Components
- `dashboard.py`: The Python-based backend server that serves real-time data to the UI.
- `kibot_dashboard.html`: The modern, high-fidelity frontend dashboard for the operator.
- `ki_cluster_monitor.py`: A specialized background service that tracks cluster-wide performance metrics and node resource usage.
