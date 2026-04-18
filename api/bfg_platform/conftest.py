"""
Platform API integration test conftest.
Each sub-directory (embedded/, standalone/) loads its own .env via its own conftest.
This parent conftest is intentionally empty — sub-conftest files take precedence.
"""
