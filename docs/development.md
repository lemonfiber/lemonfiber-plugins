# Registering a plugin, and how this repository is checked

For plugin authors and the people who maintain this list. What the list is for
the people who run a stack is in the [README](../README.md).

This repository is the registry: where a plugin is registered to be found.

**It is not a dependency.** Publishing a plugin needs nothing beyond a git
repository. lemonfiber installs a plugin from a source the operator names, reads
nothing from this repository to do it, and validates a plugin the same way
wherever it came from.
An author who never registers still has a working, installable plugin. What
registering adds is that somebody read it, and that an operator can find it
without being told the URL: an install by name resolves the name through the
signed index each release of this repository publishes, and installs the
revision it names. The
[plugin catalogue requirements](https://github.com/lemonfiber/spec/blob/main/10-functional/features/f-extensibility/f5-plugin-catalogue.md)
are the full account.

**It is not a mirror.** An entry records *where* a plugin is and the revision of
it that was read — never a copy. The plugin's own repository owns its manifest,
its recordings and its proofs, and a second copy here would be a second answer to
*what does this plugin declare*, with nothing to say which of the two an operator
installed. lemonfiber refuses two plugins of the same name from different
origins; a registry of copies would manufacture that case rather than refuse it.

## What is in it

```
plugins/
└── <id>.toml            where it is, and the revision somebody read
bundle/
├── bundle.toml          the default bundle: each first-party plugin, pinned
└── plugins/             a copy of each pinned plugin: <id>.toml at schema 1,
                         <id>/ holding its tree at schema 2
```

An entry is a pointer and nothing else:

```toml
schema = 1

[plugin]
id       = "komga"
origin   = "https://github.com/lemonfiber/plugin-komga"
revision = "8fa05ba718f70624f2c122f8c0371d47e6c90d0e"
note     = "Read comics, manga and digital magazines in a browser, and on the reading apps you already use."
```

`note` is what the plugin gives the person who runs it, in one sentence. The
README's table of plugins says the same thing, and moves with it.

`revision` is a full commit and never a tag or a branch, because review is of a
tree rather than of a name: a name can be repointed after it was read, which is
the whole of what registering it was for. Moving a plugin forward is a pull
request moving that one line, and that is the same person reading again.

## The default bundle

`bundle/bundle.toml` is the set of first-party plugins every stack is built
from, as the
[bundle contract](https://github.com/lemonfiber/spec/blob/main/20-architecture/contracts/bundle.md)
states it. lemonfiber embeds this repository and compiles the bundle in. It is
the one place this repository holds a copy of what a plugin publishes. The
file's own comments describe each field. `registry/bundle.py` reads it at
`schema = 1` and `schema = 2`, and refuses any other schema, naming both.

At **schema 1** the bundle pins each plugin by its release, the revision whose
manifest names that release's image, and the digest of that manifest, and
`bundle/plugins/<id>.toml` holds the manifest itself, copied byte for byte. Each
copy's adapter service, the one that `speaks`, is tagged at the release.

At **schema 2** the bundle also declares the stack's `[[profile]]`, `[[form]]`,
`[[wiring]]` and `[[removed]]` tables, and each `[[plugin]]` names its
`revision`, the digests of its `manifest` and its `tree`, what it `fills`, its
`stage` (`assembled` or `installed`), its `profile` and the upstream's
`last_release`. It names a `release` only where the plugin builds an image, one
of its services running an image under `ghcr.io/lemonfiber/`, and every such
image is then tagged at it. A release is three numbers without a `v`, because
the train tags no pre-release. `bundle/plugins/<id>/` holds the plugin's tree at
the pinned revision, each file at its path in the plugin's repository.

### The tree, and its digest

A plugin's tree is `plugin.toml`, every file under `config/<service id>/` for
each service the manifest declares, every recording the manifest names (each
`fixture`, wherever it appears), and every file under `conformance/`. Nothing
else is in it, no symbolic link may be, and each service's starting files are
at most 64 files and 1 MiB.

`tree` is the SHA-256 of a listing of those files, one line each: the file's
SHA-256 in lowercase hex, two spaces, its path from the repository root with `/`
between segments, and a line feed. The lines are sorted by the path's UTF-8
bytes, so `config/example-db/` sorts before `config/example/`, because `-` is
0x2d and `/` is 0x2f. A sort by path component gives another digest. The
listing is what `sha256sum` prints for the same files in that order, and
`python3 registry/tree.py <directory>` prints it and the digest for a checkout.

The vector `registry/test_bundle.py` holds the digest to, and any other reader
can be held to, is a repository holding these seven files, each written exactly
as shown, with a final line feed:

| Path | Bytes |
| --- | --- |
| `plugin.toml` | below |
| `config/example/settings.ini` | `[main]` and `port = 8080`, on two lines |
| `config/example-db/init.sql` | `CREATE TABLE seen (id INTEGER);` |
| `recordings/example/catalogue.json` | `{"status": 200}` |
| `recordings/example/unused.json` | `{}` |
| `conformance/media.serve.json` | `{}` |
| `README.md` | `# Example` |

```toml
schema_version = 1

[plugin]
id = "example"

[[service]]
id = "example"

[[service]]
id = "example-db"

[[claim]]
capability = "media.serve"

[[claim.probe]]
id = "catalogue"
fixture = "recordings/example/catalogue.json"
```

Its tree leaves out `README.md`, which is none of the four, and
`recordings/example/unused.json`, which the manifest does not name. The listing
is:

```text
6e174a2633a59381bd17b8119908c22e4e8f01c3674c97c0811d3dcd7d9c0f47  config/example-db/init.sql
275a814ae5de8dc3a28e8de2cd66fc9188651dba5d3fbcd419f6c8781f5c4fe1  config/example/settings.ini
ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356  conformance/media.serve.json
32a4e386817bdf93699b3a1188b9776f2af6a34298df7497a2efdfcc1698829f  plugin.toml
9e80cc1a864b04a50ef8b57bff6c0f51fb4e822becc0482cf95f2bcb07f95c8e  recordings/example/catalogue.json
```

and the tree digest is
`sha256:083641a4cacc0289f6d0acc96e7e1b67b2dafc17b8d5df47265eaaaf5ce35a77`.

### How a pin moves

The release train moves the pin of a plugin that builds an image. When a
first-party plugin's pin pull request merges, its repository dispatches
`bundle-bump.yml` with the merge commit and its own address, and the bump moves
that pin and its copy on one rolling pull request, `release/bundle-pins`. Only
the release App dispatches it, and only against `main`; it refuses a repository
asking to move a pin the bundle holds from another origin, and commits no copy
that is not what its pin names. At schema 2 it refuses to move a plugin that
builds no image: that pin moves by a person's pull request here. A plugin
enters the bundle through a person's pull request, which says what it fills.

### What the `bundle` job refuses

At either schema: a copy no pin names, a pin with no copy, a pinned revision
that is not on its origin's default branch, a copy that differs from what is
fetched from its origin at the pinned revision, and a pinned revision failing
what `plugins` holds a registration to.

At schema 1: a copy whose digest, id or adapter tag is not its pin's, and a
`fills` the copy neither provides nor speaks.

At schema 2, everything the bundle contract's validation names: the stack's
tables and their references to each other, a wiring that is neither a choice
of filler nor a link by name, a copy whose manifest or tree digest is not its
pin's, a file in a copy outside the plugin's tree, an assembled plugin that is
not one service speaking no contract with its claims recorded under
`recordings/<id>/`, an installed plugin whose service of its id does not
replace it or which names an in-process adapter, `[plugin].forms` that are not
exactly the forms holding its profile, a licence that is neither OSI nor, for
lemonfiber's own code and image, `Hippocratic-3.0`, a service without both
`reaches` and `asks_for`, `critical` without the egress guard's shape, a release
on a plugin that builds no image or a built image not tagged at it, and an id,
published port or proxy hostname taken by two pinned plugins, the hostnames the
proxy's configuration in its copy answers on included.

```sh
python3 registry/bundle.py --self-test   # the gate refuses what it should
python3 registry/bundle.py --offline     # the bundle and its copies, nothing fetched
python3 registry/bundle.py               # every pin, held to its origin
```

### A part's repository, written from the media stack

`registry/convert.py` writes the repository of one part of the media stack
([ADR-0045](https://github.com/lemonfiber/spec/blob/main/00-overview/decisions/0045-every-bundled-part-has-its-repository-now-and-its-adapter-later.md)).
It reads `lemonfiber-media-stack` and `plugin-template` each at a commit, so the
same two commits and the same part always write the same bytes, and writes into
an empty directory beneath the working directory:

- `plugin.toml`, the part's `services/<id>.toml` in the plugin manifest's
  vocabulary. The plugin's id and name are the service's, and `[plugin]` takes
  its `describes`, `without_it`, `upstream` and `license`. `forms` names exactly
  the forms whose closure holds the service's profile. Each wiring asking a
  capability by the service is an `[[ask]]`, and its claims are `[[claim]]`. The
  service declares `replaces` naming its own id, which is how a manifest takes
  an id and a port the bundle reserves.
- Every file under `config/<id>/`, and every recording its claims name, byte for
  byte at its path.
- plugin-template's `bundled-part/` variant laid over the template's root, as
  the template's `docs/development.md` lists, with a README and an AGENTS.md
  written for the part. The variant's own README and AGENTS.md have to be what
  this writes for the variant's part, or nothing is written.
- `proofs.json`, where `--lemonfiber` names a build of the commit the variant's
  `targets.toml` names, written by the template's reader.

It refuses, by name and writing nothing: a field the plugin manifest has no
place for, a part that builds an image, a profile, a recording or a link the
stack does not hold, a template file nothing says what becomes of, and anything
the `bundle` job would refuse of the manifest it wrote. The profile, the
upstream's last release, the choices of filler and the links by name stay the
bundle's, and it prints them for the pin, with the manifest and tree digests.

```sh
python3 registry/convert.py --self-test
python3 registry/convert.py --stack ../lemonfiber-media-stack --stack-at <commit> \
  --template ../plugin-template --template-at <commit> \
  [--lemonfiber <build>] sabnzbd out/plugin-sabnzbd
```

## How to register

1. **Have a plugin that passes its own CI.** Copy
   [`plugin-template`](https://github.com/lemonfiber/plugin-template), replace
   the service, record your fixtures, and get your own repository green. Nothing
   here can be registered that would not pass there.
2. **Fork this repository and add one file**, `plugins/<your-id>.toml`, carrying
   the fields above — `note` is the only optional one. The id is your plugin's
   `[plugin].id`, and the file is named for it.
3. **Point `revision` at the commit you want read.** Not `main` — the exact
   commit.
4. **Add a row for it to the table in the README**, saying what it gives the
   person who runs it.
5. **Open a pull request.** CI runs before anybody looks (below). If it is red,
   the message names what is wrong and where; fix it and push.
6. **A person reads the diff and the revision it points at**, and merges. That is
   the whole of what being in this list means: a schema that was checked,
   proofs that ran, and a person who read it. It is not a reading of the image.
   A manifest can be read line by line and a container image cannot, which is
   why the image is pinned by digest rather than vouched for.

Updating is the same thing with one line changed. Removing a plugin is deleting
its file; nothing installed stops working, because nothing installed resolves
anything here.

## What CI checks on a registration

Four jobs, and the order is deliberate — the cheap answer about your *entry*
comes before anything is fetched, so a reviewer is never left wondering whether
the problem is the registration or the plugin.

| Job | What it decides |
| --- | --- |
| `entries` | Every entry says what an entry may say: a plugin id that matches its filename, an `https` origin with no credentials, a full commit, no field this registry does not read, and no origin registered twice under two names. Its own rules are self-tested first, so a green run is a run whose gate still refuses things. |
| `harness` | `.github/reader/` is byte-identical to `plugin-template`'s. A registry holding its own fork of the harness would be a second opinion about what a manifest means, and plugin repositories would go green against a rule this one had dropped. |
| `template` | The template an author starts from, held to those same commands: it validates and proves unmodified, or this repository says so. The byte-diff above answers whether the two harnesses agree; this answers whether the template still passes them. Neither of the other gates asks it — a byte-diff fires on a change to the harness and the template's own CI fires on a commit there, and neither fires when this repository moves to a release that reads the template differently. |
| `plugins` | Each registered revision is fetched, and out of the data in it the release this repository targets is asked `lemonfiber plugin claims`: the manifest against the schema, capability vocabulary and extension points that release publishes, every declared reach checked statically, and every probe, proof and contributed check against that plugin's own recorded responses. |

They are asked of the lemonfiber release this
repository's [`targets.toml`](../targets.toml) names, fetched by
`.github/reader/reader.py` and checked against its published digest, and they
compare that release with the one each plugin's own `targets.toml` names,
reporting a difference rather than refusing on it. A capability in
`[requires]` that release does not offer a plugin is reported by it and not
refused here, as in every plugin repository.

**Nothing from a registered repository is executed.** The manifest,
the recordings and `targets.toml` are copied out of the fetched tree and
everything else is left where it lies; the programs that read them are this
repository's own. lemonfiber draws the same line on an operator's machine, for the same reason: a catalogue that ran a
stranger's script in order to decide whether the stranger's data was acceptable
would be answering the question by doing the thing the question is about.

The proofs run against recordings rather than against a live service, and are
reported as what they are: a claim about what a
plugin declares, which is weaker than a claim about a service that answered.

Run any of it yourself:

```sh
python3 registry/entry.py --self-test   # the gate refuses what it should
python3 registry/entry.py               # every entry, read
python3 registry/check.py               # every registration, held to everything
python3 registry/check.py --only komga  # one of them
python3 registry/check.py --template    # the template, held to the same
```

`check.py` needs `git` and the network, to fetch the release and the registered
revisions.

## Why `plugin-template` is not registered here

It is the repository an author copies, and what it installs — Kavita — is there
so that its proofs are proofs rather than because anybody should run it. Putting
it in a list an operator browses for something to install would be offering a
teaching artefact as a thing to use.

It is held to the format all the same, in two places and for two different
reasons. The spec's [`70-operations/plugins.toml`](https://github.com/lemonfiber/spec/blob/main/70-operations/plugins.toml)
registers it for lemonfiber's release process, so a lemonfiber release that
breaks what every author starts from is stopped before it is cut. And the `template` job above runs *these* checks
over it on every change here, because an author's own CI is a copy of these
commands and the template is what they copy: it has to validate and prove
unmodified against them, or the first thing somebody meets is a starting point
that does not pass.

Neither of those is a registration. *Is this good to install* and *does the
thing every author begins with still hold* are different questions, and only the
first of them is what the list in `plugins/` answers.

## What this never becomes

**Not a runtime dependency.** Nothing published here is resolved by
an installed plugin while it runs. The moment it were, every operator's stack
would depend on this repository being reachable.

**Not a service.** No backend, no database, no state beyond the
repository. A catalogue that needed operating would be a second product, and it
would be one this project has said it does not build.

**Not a walled garden.** The curated lane is not the only road: an operator's
own source is held to the same technical terms. This list has one reviewer.

## Licence

`license` in a plugin's manifest is a fact about the upstream service it
configures rather than about anything here. The licence of this repository is in
the [README](../README.md#licence).
