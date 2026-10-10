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
└── plugins/<id>.toml    a copy of each pinned manifest
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
from. lemonfiber embeds this repository and compiles the bundle in, so it pins
each plugin by its release, the revision whose manifest names that release's
image, and the digest of that manifest, and `bundle/plugins/<id>.toml` holds
the manifest itself, copied byte for byte. It is the one copy this repository
holds. The file's own comments describe each field.

The release train moves the pins. When a first-party plugin's pin pull request
merges, its repository dispatches `bundle-bump.yml` with the merge commit and
its own address, and the bump moves that pin and its copy on one rolling pull
request, `release/bundle-pins`. It refuses a repository asking to move a pin
the bundle holds from another origin. A plugin enters
the bundle through a person's pull request, which says what it fills.

The `bundle` job refuses a copy no pin names, a pin with no copy, a copy whose
digest, id or adapter tag is not its pin's, a `fills` the copy neither provides
nor speaks, a pinned revision that is not on its origin's default branch, and a
copy that differs from the manifest fetched from its origin at the pinned
revision. It then holds that revision to everything `plugins`
holds a registration to.

```sh
python3 registry/bundle.py --self-test   # the gate refuses what it should
python3 registry/bundle.py               # every pin, held to its origin
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
