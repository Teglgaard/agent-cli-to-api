#!/usr/bin/env python3
"""
Integration test: Verify cursor-agent token usage is returned via the API.

This test uses a mock cursor-agent CLI that simulates real cursor-agent output
including token usage data. It then calls the agent-cli-to-api server and
verifies that the usage data is correctly returned in both streaming and
non-streaming responses.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def create_mock_cursor_agent(mock_dir: Path) -> Path:
    """Create a mock cursor-agent executable that returns test data with usage."""
    mock_script = mock_dir / "mock-cursor-agent"
    
    script_content = '''#!/usr/bin/env python3
import sys
import json

# Read prompt from stdin
prompt = sys.stdin.read()

# Output sequence simulating cursor-agent
events = [
    {
        "type": "system",
        "subtype": "init",
        "model": "claude-sonnet-4",
        "apiKeySource": "test",
        "permissionMode": "auto",
        "session_id": "test-123"
    },
    {
        "type": "assistant",
        "message": {
            "content": "Processing your request: "
        }
    },
    {
        "type": "assistant",
        "message": {
            "content": "Processing your request: analyzing code..."
        }
    },
    {
        "type": "assistant",
        "message": {
            "content": "Processing your request: analyzing code... Done! Here's the solution."
        }
    },
    {
        "type": "result",
        "result": "Processing your request: analyzing code... Done! Here's the solution.",
        "usage": {
            "inputTokens": 1250,
            "outputTokens": 89,
            "cacheReadTokens": 8500,
            "cacheWriteTokens": 0
        }
    }
]

for evt in events:
    print(json.dumps(evt), flush=True)
'''
    
    mock_script.write_text(script_content)
    mock_script.chmod(0o755)
    return mock_script


async def test_non_streaming():
    """Test non-streaming mode returns token usage."""
    print("\n" + "=" * 80)
    print("TEST: Non-streaming API endpoint with token usage")
    print("=" * 80)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "http://127.0.0.1:8000/v1/chat/completions",
            json={
                "model": "cursor-agent",
                "messages": [
                    {"role": "user", "content": "Test prompt for token usage"}
                ],
                "stream": False
            }
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        print("\nAPI Response:")
        print(json.dumps(data, indent=2))
        
        # Verify structure
        assert "choices" in data, "Response should have choices"
        assert len(data["choices"]) > 0, "Should have at least one choice"
        assert "message" in data["choices"][0], "Choice should have message"
        assert "content" in data["choices"][0]["message"], "Message should have content"
        
        # Verify usage is present
        assert "usage" in data, "Response should have usage field"
        usage = data["usage"]
        
        print("\n✅ Response structure is correct")
        print(f"\nToken usage:")
        print(f"  Prompt tokens: {usage.get('prompt_tokens')}")
        print(f"  Completion tokens: {usage.get('completion_tokens')}")
        print(f"  Total tokens: {usage.get('total_tokens')}")
        
        # Verify usage values
        assert usage["prompt_tokens"] == 1250, f"Expected 1250 prompt_tokens, got {usage['prompt_tokens']}"
        assert usage["completion_tokens"] == 89, f"Expected 89 completion_tokens, got {usage['completion_tokens']}"
        assert usage["total_tokens"] == 1339, f"Expected 1339 total_tokens, got {usage['total_tokens']}"
        
        # Verify cache details
        if "prompt_tokens_details" in usage:
            print(f"  Cached tokens: {usage['prompt_tokens_details'].get('cached_tokens')}")
            assert usage["prompt_tokens_details"]["cached_tokens"] == 8500
        
        print("\n✅ Token usage correctly extracted and returned!")
        return True


async def test_streaming():
    """Test streaming mode returns token usage in final chunk."""
    print("\n" + "=" * 80)
    print("TEST: Streaming API endpoint with token usage")
    print("=" * 80)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream(
            "POST",
            "http://127.0.0.1:8000/v1/chat/completions",
            json={
                "model": "cursor-agent",
                "messages": [
                    {"role": "user", "content": "Test streaming with token usage"}
                ],
                "stream": True
            }
        ) as response:
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"
            
            print("\nStreaming chunks:")
            content_parts = []
            last_usage = None
            
            async for line in response.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                
                if line.startswith("data: "):
                    data_str = line[6:]
                    
                    if data_str == "[DONE]":
                        print("  [DONE]")
                        break
                    
                    try:
                        chunk = json.loads(data_str)

                        if "choices" in chunk and chunk["choices"]:
                            delta = chunk["choices"][0].get("delta", {})
                            if "content" in delta:
                                content = delta["content"]
                                content_parts.append(content)
                                print(f"  Delta: {repr(content)}")

                            if "usage" in chunk:
                                last_usage = chunk["usage"]
                                print(f"\n  Usage chunk: {json.dumps(chunk['usage'], indent=4)}")
                    except json.JSONDecodeError:
                        continue

            full_content = "".join(content_parts)
            print(f"\nAssembled content: {repr(full_content)}")

            assert len(content_parts) > 0, "Should have received content"
            assert full_content, "Should have assembled content"
            assert last_usage is not None, (
                "Final SSE chunk should include OpenAI-style usage (gateway adds it before [DONE])"
            )
            assert last_usage.get("prompt_tokens") == 1250, last_usage
            assert last_usage.get("completion_tokens") == 89, last_usage
            assert last_usage.get("total_tokens") == 1339, last_usage
            assert last_usage.get("prompt_tokens_details", {}).get("cached_tokens") == 8500

            print(
                "\n✅ Streaming returns token usage on the final chunk "
                "(downstream e.g. LiteLLM / Claude can consume this)."
            )
            return True


async def main():
    """Run all integration tests."""
    print("\n" + "=" * 80)
    print("CURSOR-AGENT TOKEN USAGE - API INTEGRATION TEST")
    print("=" * 80)
    
    # Create temporary directory for mock cursor-agent
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_dir = Path(tmpdir)
        mock_cursor_agent = create_mock_cursor_agent(mock_dir)
        
        print(f"\nCreated mock cursor-agent: {mock_cursor_agent}")
        
        # Start the server with mock cursor-agent
        env = os.environ.copy()
        env["CURSOR_AGENT_BIN"] = str(mock_cursor_agent)
        env["CURSOR_AGENT_WORKSPACE"] = str(Path.cwd())
        env["LOG_EVENTS"] = "true"
        
        print("\nStarting agent-cli-to-api server...")
        server_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "codex_gateway.server:app", "--host", "127.0.0.1", "--port", "8000"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        try:
            # Wait for server to start
            print("Waiting for server to be ready...")
            await asyncio.sleep(3)
            
            # Check if server is running
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get("http://127.0.0.1:8000/healthz")
                    print(f"✅ Server is ready (status: {response.status_code})")
            except Exception as e:
                print(f"⚠️ Health check failed (continuing anyway): {e}")
            
            # Run tests
            success = True
            
            try:
                await test_non_streaming()
            except Exception as e:
                print(f"\n❌ Non-streaming test failed: {e}")
                import traceback
                traceback.print_exc()
                success = False
            
            try:
                await test_streaming()
            except Exception as e:
                print(f"\n❌ Streaming test failed: {e}")
                import traceback
                traceback.print_exc()
                success = False
            
            if success:
                print("\n" + "=" * 80)
                print("🎉 ALL INTEGRATION TESTS PASSED!")
                print("=" * 80)
                print("\nResults:")
                print("  ✅ Non-streaming mode returns token usage")
                print("  ✅ Streaming mode includes usage on the final chunk")
                print("  ✅ Cache tokens are properly tracked")
                print("\nCursor-agent token usage is now fully functional!")
            else:
                print("\n" + "=" * 80)
                print("❌ SOME TESTS FAILED")
                print("=" * 80)
                sys.exit(1)
                
        finally:
            # Stop server
            print("\nStopping server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
