# Agent instructions

## Feature isolation: one worktree per feature

HomeGame uses two kinds of checkout. The **anchor tree** is the clone at the repository
root: it owns integration, the ODD feature documents in `odd/`, and the ignored local
files. A **feature worktree** is a throwaway sibling checkout under `.worktrees/<slug>`
that holds exactly one feature branch. Never implement a feature directly in the anchor
tree.

```
/home/leonel/github/home-game                  anchor: develop, odd/, .env, docker-compose.yml
/home/leonel/github/home-game/.worktrees/<slug>  feature: feat/<slug> only
```

`.worktrees/` is git-ignored, so worktree directories never show up in the anchor's
`git status` and never reach a commit.

### Create one before the first source write

From the anchor tree, with `<slug>` a short kebab-case name for the feature:

```sh
slug=<slug>
git worktree add ".worktrees/$slug" -b "feat/$slug" develop
cd ".worktrees/$slug"
cp ../../.env ../../docker-compose.yml .
sed -i "s/^COMPOSE_PROJECT_NAME=.*/COMPOSE_PROJECT_NAME=home-game-$slug/" .env
sed -i "s/^FRONTEND_PORT=.*/FRONTEND_PORT=<free port>/" .env
ln -s ../../odd odd
```

Do all four steps or the worktree is not usable:

1. `git worktree add` gives the checkout its own branch. The anchor stays on `develop`
   and is never the place where a feature is edited.
2. `.env` and `docker-compose.yml` are git-ignored, so a fresh worktree has neither and
   no Compose command would run. They must be copied, not shared.
3. **`COMPOSE_PROJECT_NAME` must be overridden.** `.env` pins it to `home-game-local`, so
   two checkouts sharing the value share one Compose project: `make up` in the worktree
   would recreate the anchor's containers against the worktree's bind mounts, and
   `make test` would then run against whichever tree was started last. That is a false
   gate, not a slow one. `FRONTEND_PORT` needs a free port for the same reason: two
   running stacks cannot bind one port.
4. `ln -s ../../odd odd` keeps the ODD feature documents in one place. `odd/` is
   git-ignored, so it does not travel with a branch; the symlink lets the worktree read and
   write `odd/tasks/<slug>.md` without a second copy that would drift.

Verify the isolation before writing code:

```sh
docker compose config | grep -m1 '^name:'   # must print home-game-<slug>, never home-game-local
```

### Work, verify, merge, remove

Work and commit inside `.worktrees/<slug>`. The gates run there, against that worktree's
own containers, database volume, and bind mounts:

```sh
make up            # own project name, own postgres_data volume, starts empty and migrates
make test
make test-frontend
```

Merge from the anchor tree, then delete the checkout:

```sh
cd /home/leonel/github/home-game
git checkout develop
git merge --ff-only feat/<slug>
cd ".worktrees/<slug>" && docker compose down -v   # the stack and its volume belong to the feature
cd /home/leonel/github/home-game
git worktree remove ".worktrees/<slug>"
git branch -d "feat/<slug>"
```

`docker compose down -v` before `git worktree remove` matters: the worktree directory is a
Compose project root, and removing it first leaves an orphaned project that later
`docker compose` calls cannot address.

### Not replicated into a worktree

`.codegraph/` (repository index) and `.atl/` (skill registry cache) are anchor-local
artifacts. A worktree that needs the code graph initializes its own; do not copy them.
