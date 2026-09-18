#!/usr/bin/env node
/**
 * Mock Dokploy MCP for local testing
 */

const http = require('http');

const port = parseInt(process.env.MCP_HTTP_PORT || '8000');
const host = process.env.MCP_HOST || '0.0.0.0';

const server = http.createServer((req, res) => {
  res.setHeader('Content-Type', 'application/json');

  if (req.url === '/health' && req.method === 'GET') {
    res.writeHead(200);
    res.end(JSON.stringify({
      status: 'ok',
      service: 'dokploy-mcp-test'
    }));
  } else if (req.url === '/' && req.method === 'GET') {
    res.writeHead(200);
    res.end(JSON.stringify({
      service: 'Dokploy MCP',
      version: '1.0.0-test',
      tools_available: [
        'list-projects', 'list-services', 'deploy', 'logs', 'status'
      ],
      note: 'Mock server - full version requires DOKPLOY_URL and DOKPLOY_API_KEY'
    }));
  } else {
    res.writeHead(404);
    res.end(JSON.stringify({
      success: false,
      message: 'Requires DOKPLOY_URL and DOKPLOY_API_KEY',
      error: 'Not configured for mock testing'
    }));
  }
});

server.listen(port, host, () => {
  console.log(`Starting Dokploy MCP (mock) on ${host}:${port}`);
});
