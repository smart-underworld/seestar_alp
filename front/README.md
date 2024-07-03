The initial name for this web interface is "Simple Seestar Controller". The
intent was to keep it fairly simple and lightweight.

Deliberate design decisions:
1. Focus implementation on Python.  This aligns it with the rest of the seestar_alp code.
2. Minimize front-end Javascript. (For the same reason as number 1.) 
3. Minimize the number of extra dependencies, especially heavyweight ones.  (At least for now)
4. Wherever possible, use HATEOAS (Hypertext As The Engine of Application State).
