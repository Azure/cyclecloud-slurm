#include "stdio.h"
#include "stdlib.h"
#include "slurm/slurm_errno.h"
#include "src/common/slurm_topology.h"


// useful for testing purposes to make linking trivial
// #ifndef info
//   #define info(...) printf(__VA_ARGS__); printf("\n")
// #endif

// #ifndef verbose
//   #define verbose(...) info(__VA_ARGS__)
// #endif

// #define cverbose info


// required by the slurm plugin system
const char plugin_name[]        = "topology cyclecloud plugin";
const char plugin_type[]        = "topology/cyclecloud";
const uint32_t plugin_version   = SLURM_VERSION_NUMBER;


typedef struct node_struct {
    char nodearray[256];
    char placement_group_id[256];
    char hostname[256];
} node;


typedef struct node_list_struct {
    node* data;
    struct node_list_struct* next;
} node_list;


node_list* _new_node_list() {
    node_list* ret = malloc(sizeof(node_list));

    ret->next = NULL;
    return ret;
};
                                                                                                                                      

void _free_node_list(const node_list* list){
    node_list* iter = list;

    while (iter) {
        node_list* old = iter;
        iter = old->next;
        free(old->data);
        old->next = NULL;
        old->data = NULL;
        free(old);
    }
}


node_list* _parse_cyclecloud_topography(const char* path) {
    info("CycleCloud: parsing %s", path);

    FILE* fp = fopen(path, "r");
    char buffer[1024];
    node_list* list = NULL;
    node_list* root = NULL;
    
    if (!fp) {
        error("CycleCloud: could not read %s", path);
        free(list);
        return NULL;
    }
    
    while(fgets(buffer, 1024, (FILE*) fp)) {
        
        char* iter = buffer;
        info("CycleCloud: parsing %s", buffer);
        if (list) {
            list->next = _new_node_list();
            list = list->next;
        } else {
            list = _new_node_list();
            root = list;
        }

        list->data = malloc(sizeof(node));

        char* tok = strtok_r(iter, ",", &iter);
        if (!tok) {
            error("Could not parse line cyclecloud topogrophy line: '%s'", buffer);
            _free_node_list(list);
            return NULL;
        }
        strcpy(list->data->nodearray, tok);

        tok = strtok_r(iter, ",", &iter);
        if (!tok) {
            error("Could not parse line cyclecloud topogrophy line: '%s'", buffer);
            _free_node_list(list);
            return NULL;
        }
        strcpy(list->data->placement_group_id, tok);

        tok = strtok_r(iter, ",", &iter);
        if (!tok) {
            error("Could not parse line cyclecloud topogrophy line: '%s'", buffer);
            _free_node_list(list);
            return NULL;
        }
        strcpy(list->data->hostname, tok);
        // strip off new lines
        char *newline;
        if ((newline=strchr(list->data->hostname, '\n')) != NULL) {
            *newline = '\0';
        }
        if ((newline=strchr(list->data->hostname, '\r')) != NULL) {
            *newline = '\0';
        }
    
        info("CycleCloud: parsed %s %s %s", list->data->nodearray, list->data->placement_group_id, list->data->hostname);
    }

    fclose(fp);

    return root;
}



extern int init(void)
{
    info("CycleCloud: init");
	return SLURM_SUCCESS;
}

extern int topo_build_config(void)
{
    info("CycleCloud: build config");
    return SLURM_SUCCESS;
}

extern bool topo_generate_node_ranking(void)
{
        return true;
}


/*
 * fini() is called when the plugin is removed.
 */
extern int fini(void)
{
	return SLURM_SUCCESS;
}


node* _node_list_get(const node_list* list, const char* node_name) {
    info("CycleCloud: enter _node_list_get %s", node_name);
    while (list && strcmp(list->data->hostname, node_name) != 0) {
        list = list->next;
    }

    if (list) {
        info("1CycleCloud: found %s!", node_name);
        return list->data;
    }

    return NULL;
}
 
/*
 * topo_get_node_addr - build node address and the associated pattern
 *      based on the topology information
 *
 * example of output :
 *      address : execute.pg0.ip-0A000000
 *      pattern : switch.switch.node
 */
extern int topo_get_node_addr(char* node_name, char** paddr, char** ppattern)
{
    info("CycleCloud: enter topo_get_node_addr %s", node_name);
    char* topology_file = getenv("CYCLECLOUD_TOPOLOGY_FILE");
    info("CycleCloud: CYCLECLOUD_TOPOLOGY_FILE=%s", topology_file);
    if (topology_file == NULL) {
        topology_file = "/opt/cycle/jetpack/topology.csv";
    }

    node_list* nodes = _parse_cyclecloud_topography(topology_file);
    if (nodes == NULL) {
        error("Failed to parse %s", topology_file);
        return SLURM_ERROR;
    }


    node* node = _node_list_get(nodes, node_name);
    if (!node) {
        info("CycleCloud: Failed");
        error("CycleCloud: Unknown node name: %s", node_name);
        _free_node_list(nodes);
        return SLURM_ERROR;
    }
    
    *paddr = malloc(sizeof(char) * 512);
    memset(*paddr, 0, sizeof(char) * 512);
    *ppattern = malloc(sizeof(char) * 32);
    memset(*ppattern, 0, sizeof(char) * 32);

    info("paddr2 %s", paddr);
    info("paddr %s", *paddr);
    strcat(*paddr, node->nodearray);
    info("paddr %s", *paddr);
    strcat(*paddr, ".");
    info("paddr %s", *paddr);
    strcat(*paddr, node->placement_group_id);
    info("paddr %s", *paddr);
    strcat(*paddr, ".");
    info("paddr %s", *paddr);
    strcat(*paddr, node->hostname);
    info("paddr %s", *paddr);
    info("paddr %s", *ppattern);
	strcat(*ppattern, "switch.switch.node");
    info("paddr %s", *ppattern);
    _free_node_list(nodes);
    info("free");
    return 0;
}
