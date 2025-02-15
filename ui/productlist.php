<!-- productlist.php (POS component) -->
<?php
include_once 'connectdb.php';
session_start();
include_once "header.php";

if (!isset($_SESSION['email']) || $_SESSION['role'] === 'Cashier') { 
    echo "<script>
            alert('Sorry, you can\'t access this. Please contact the Admin.');
            window.location.href = '../index.php';
          </script>"; 
    exit;
}
?> 


<!-- Content Wrapper. Contains page content -->
<div class="content-wrapper">
    <!-- Content Header (Page header) -->
    <div class="content-header">
        <div class="container-fluid">
            <div class="row mb-2">
                <div class="col-sm-6">
                    <h1 class="m-0">Product Inventory</h1>
                </div>
            </div>
        </div>
    </div>

    <!-- Main content -->
    <div class="content">
        <div class="container-fluid">
            <div class="row">
                <div class="col-lg-12">
                    <div class="card card-primary card-outline">
                        <div class="card-header">
                            <h5 class="m-0">Product List</h5>
                        </div>
                        <div class="card-body">
                            <table class="table table-striped table-hover" id="table_product">
                                <thead class="thead-dark">
                                    <tr>
                                        <th>Barcode</th>
                                        <th>Product</th>
                                        <th>Category</th>
                                        <th>Description</th>
                                        <th>Stock</th>
                                        <th>Purchase Price</th>
                                        <th>Sale Price</th>
                                        <th>Image</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php
                                    $select = $pdo->prepare("
                                        SELECT p.*, c.category_name 
                                        FROM products p
                                        JOIN categories c ON p.category_id = c.category_id
                                        ORDER BY p.product_id ASC
                                    ");
                                    $select->execute();

                                    while ($row = $select->fetch(PDO::FETCH_OBJ)) {
                                        echo '
                                        <tr>
                                            <td>' . htmlspecialchars($row->barcode) . '</td>
                                            <td>' . htmlspecialchars($row->product_name) . '</td>
                                            <td>' . htmlspecialchars($row->category_name) . '</td>
                                            <td>' . htmlspecialchars(substr($row->description, 0, 30)) . '...</td>
                                            <td class="' . ($row->stock <= $row->reorder_level ? 'text-danger font-weight-bold' : '') . '">
                                                ' . $row->stock . '
                                            </td>
                                            <td>₱' . number_format($row->purchase_price, 2) . '</td>
                                            <td>₱' . number_format($row->sale_price, 2) . '</td>
                                            <td>
                                                <img src="productimages/' . htmlspecialchars($row->image) . '" 
                                                     class="img-thumbnail" 
                                                     width="60" 
                                                     alt="' . htmlspecialchars($row->product_name) . '">
                                            </td>
                                            <td>
                                                <div class="btn-group">
                                                    <a href="printbarcode.php?id=' . $row->product_id . '" 
                                                       class="btn btn-dark btn-sm" 
                                                       data-toggle="tooltip" 
                                                       title="Print Barcode">
                                                        <i class="fas fa-barcode"></i>
                                                    </a>
                                                    <a href="viewproduct.php?id=' . $row->product_id . '" 
                                                       class="btn btn-info btn-sm" 
                                                       data-toggle="tooltip" 
                                                       title="View Details">
                                                        <i class="fas fa-eye"></i>
                                                    </a>
                                                    <a href="editproduct.php?id=' . $row->product_id . '" 
                                                       class="btn btn-primary btn-sm" 
                                                       data-toggle="tooltip" 
                                                       title="Edit Product">
                                                        <i class="fas fa-edit"></i>
                                                    </a>
                                                    <button class="btn btn-danger btn-sm btndelete" 
                                                            data-id="' . $row->product_id . '" 
                                                            data-toggle="tooltip" 
                                                            title="Delete Product">
                                                        <i class="fas fa-trash-alt"></i>
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>';
                                    }
                                    ?>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<?php include_once "footer.php"; ?>
<script>
$(document).ready(function() {
    // Initialize DataTable
    var table = $('#table_product').DataTable({
        "columnDefs": [
            { "orderable": false, "targets": [8] },
            { "className": "text-center", "targets": [7,8] }
        ],
        "responsive": true
    });

    // Initialize tooltips
    $('[data-toggle="tooltip"]').tooltip();

    // Use delegated event binding for delete buttons
    $(document).on('click', '.btndelete', function() {
        console.log("Delete button clicked"); // For debugging
        var productId = $(this).data('id');
        var row = $(this).closest('tr');

        Swal.fire({
            title: 'Confirm Delete',
            text: "Are you sure you want to delete this product?",
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#3085d6',
            confirmButtonText: 'Delete'
        }).then((result) => {
            if (result.isConfirmed) {
                $.ajax({
                    url: 'productdelete.php',
                    type: 'POST',
                    data: { pidd: productId },
                    dataType: 'json',
                    success: function(response) {
                        console.log("AJAX Response:", response); // Debug output
                        if (response.success) {
                            Swal.fire('Deleted!', response.message, 'success')
                                .then(() => {
                                    // Reload the page to reflect changes
                                    location.reload();
                                });
                        } else {
                            console.log("Server Error Response:", response);
                            Swal.fire('Error!', response.error || 'Failed to delete product', 'error');
                        }
                    },
                    error: function(xhr, status, error) {
                        console.log("AJAX Error:", status, error, xhr.responseText);
                        Swal.fire('Error!', 'Failed to delete product', 'error');
                    }
                });
            }
        });
    });
});
</script>


