# SAFA-Artifacts

To cite the dataset and artifacts used in this study, please cite the below DOI

[![DOI](https://zenodo.org/badge/162755376.svg)](https://zenodo.org/badge/latestdoi/162755376)


## Data Set
In this repository we make a set of artifacts available that were used for experiments in the paper:

Leveraging Artifact Trees to Evolve and Reuse Safety Cases 
Ankit Agrawal, Seyedehzahra Khoshmanesh, Michael Vierhauser, Mona Rahimi, Jane Cleland-Huang, Robyn Lutz, 
International Conference on Software Engineering, Montreal, Canada, 2019

The paper is available in preprint form [here](ICSE_2019_SAFA_preprint.pdf). 

The primary artifacts are two .JSON files which contain hazards, requirements, design definitions, source code, acceptance tests, and environmental assumptions linked together by traceability links to form a tree structure.  The root node of the tree is a single hazard that is mitigated through the contributions of the other artifacts.

The key contribution of this dataset is therefore the raw data for two versions of the Dronology System [Version 0](/V0-simplified.json) and  [Version 1](/V1-simplified.json) released as JSON files. The data set is easily reusable through writing a simple .JSON parser.  For additional information about Dronology please visit [https://dronology.info](https://dronology.info).

## Overview of the SAFA Process

Our approach, as described in our ICSE paper generates the following trees from the .JSON files.
![SAFA Approach](/SAFA_process.png).

We briefly describe the purpose of each type of tree. Safety Assurance Cases (SACs) are increasingly used to guide and evaluate the safety of software-intensive systems. They are used to construct a hierarchically organized set of claims, arguments, and evidence in order to provide a structured argument that a system is safe for use. 
However, as the size of the system evolves and grows in size, a SAC can be difficult to maintain.  In this paper we utilize design science to develop a novel solution for identifying areas of a SAC that are affected by changes to the system. Moreover, we generate actionable recommendations for updating the SAC, including its underlying artifacts and trace links, in order to evolve an existing safety case for use in a new version of the system.  

Our approach, **Safety Artifact Forest Analysis** (SAFA), leverages traceability to automatically compare software artifacts from a previously approved or certified version with a new version of the system. We identify critical changes in the system and visualize them in a Delta View of the two versions. We further provide  actionable recommendations that an analyst or developer can take to evolve the safety case. We evaluate our approach using the [Dronology](http://www.dronology.info) system for monitoring and coordinating the actions of cooperating, small Unmanned Aerial Vehicles. Results from a user study show that SAFA helped users to identify changes that potentially impacted system safety and provided information that could be used to help maintain and evolve a SAC. 

## Visual Perspective of Artifacts
Because the .JSON files do not provide a visual perspective of the artifacts and trace links that we are sharing, we further provide processed Graphviz files for both versions of the Artifact Trees ([V0](/V0_raw_artifacts_GraphvizFiles), [V1](/V1_raw_artifacts_GraphvizFiles)) as well as the [Delta Trees](/Delta_gvFiles).  The graphviz files can be modified with annotations.

Each SAFA tree initiates from a root hazard.  For each hazard we therefore provide views of its associated artifact tree and safety tree for each version (V1 and V2), and also the delta view depicting changes in the two versions.

1.  [UAV-1006](/UAV-1006.md) - UAV receives a goto directive that causes it to fly into terrain.
2.  [UAV-1007](/UAV-1007.md) - UAV flies into a fixed stationary object such as a building or tree.
3.  [UAV-1009](/UAV-1009.md) - Midair collision during flight execution.
4.  [UAV-1018](/UAV-1018.md) - Satellite signals are lost causing the UAV to lose accurate localization and fly in seemingly                                  random directions to achieve its target
5.  [UAV-1021](/UAV-1021.md) - UAV compass calibration error causes UAV to fly in incorrect direction.
6.  [UAV-1031](/UAV-1031.md) - An untrusted UAV registers with Dronology, fails to comply with commands, and creates chaos in                                the airspace.
7.  [UAV-1101](/UAV-1101.md) - UAV flies above the altitude permitted by FAA regulations.
8.  [UAV-861](/UAV-861.md)   - Collision occurs between UAVs at takeoff.
9.  [UAV-906](/UAV-906.md)   - UAV is no longer controllable from Dronology due to communication loss.
10. [UAV-930](/UAV-930.md)   - UAV collides with another UAV when Dronology issues RTL. 
11. [UAV-945](/UAV-945.md)   - Area mapping provides insufficient coverage during search and rescue.
12. [UAV-947](/UAV-947.md)   - Battery fails during flight.
13. [UAV-999](/UAV-999.md)   - UAV receives waypoint commands but does not obey them




