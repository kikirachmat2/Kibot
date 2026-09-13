import time
import logging

class CircuitBreaker:
    def __init__(self, name, max_failures=3, reset_after_sec=300):
        self.name = name
        self.failures = 0
        self.max_failures = max_failures
        self.reset_after = reset_after_sec
        self.opened_at = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.logger = logging.getLogger(f"CircuitBreaker-{name}")

    def record_failure(self):
        self.failures += 1
        self.logger.warning(f"[{self.name}] Failure recorded ({self.failures}/{self.max_failures})")
        if self.failures >= self.max_failures:
            if self.state != "OPEN":
                self.state = "OPEN"
                self.opened_at = time.time()
                self.logger.error(f"[{self.name}] CIRCUIT OPENED! Stopping retries for {self.reset_after}s")
                
                # Report to Sovereign Council if possible
                try:
                    from Core.sovereign_council import SovereignCouncil
                    import asyncio
                    council = SovereignCouncil()
                    # Trigger async deliberation in a non-blocking way
                    asyncio.create_task(council.deliberate({
                        "type": "CIRCUIT_BREAKER_OPEN",
                        "component": self.name,
                        "snapshot": {"failures": self.failures, "timestamp": time.time()}
                    }))
                except Exception as e:
                    self.logger.warning(f"Could not report to Council: {e}")
                
                return "ESCALATE"
        return "RETRY"

    def record_success(self):
        if self.state != "CLOSED":
            self.logger.info(f"[{self.name}] Success! Circuit closed.")
        self.failures = 0
        self.state = "CLOSED"
        self.opened_at = None

    def can_attempt(self):
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self.opened_at is not None and (time.time() - self.opened_at > self.reset_after):
                self.logger.info(f"[{self.name}] Reset timeout reached. Moving to HALF_OPEN")
                self.state = "HALF_OPEN"
                return True
            return False
        if self.state == "HALF_OPEN":
            return True
        return False

    def get_status(self):
        return {
            "name": self.name,
            "state": self.state,
            "failures": self.failures,
            "time_until_reset": max(0, int(self.reset_after - (time.time() - self.opened_at))) if self.opened_at else 0
        }
